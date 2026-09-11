import hashlib
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from werkzeug.security import check_password_hash, generate_password_hash


os.environ.setdefault('SECRET_KEY', 'test-secret-key')
os.environ.setdefault('SESSION_COOKIE_SECURE', 'false')
os.environ.setdefault(
    'TOURNOIS_DB',
    os.path.join(tempfile.gettempdir(), f'jap-test-bootstrap-{os.getpid()}.db'),
)

import app as jap_app  # noqa: E402


class SecurityTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        jap_app.DB_PATH = os.path.join(self.temp_dir.name, 'jap-test.db')
        jap_app.init_db()
        jap_app.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        self._seed_database()

    def _seed_database(self):
        with jap_app.get_db() as db:
            now = 'test'
            self.club_a = db.execute(
                "SELECT id FROM clubs WHERE slug='arena18'"
            ).fetchone()['id']
            db.execute(
                'INSERT INTO users (club_id,email,password,nom,role,cree_le) VALUES (?,?,?,?,?,?)',
                (self.club_a, 'a@example.test', generate_password_hash('password-a'),
                 'Admin A', 'superadmin', now),
            )
            db.execute(
                'INSERT INTO clubs (nom,slug,actif,cree_le) VALUES (?,?,1,?)',
                ('Club B', 'club-b', now),
            )
            self.club_b = db.execute(
                "SELECT id FROM clubs WHERE slug='club-b'"
            ).fetchone()['id']
            db.execute(
                'INSERT INTO users (club_id,email,password,nom,role,cree_le) VALUES (?,?,?,?,?,?)',
                (self.club_b, 'b@example.test', generate_password_hash('password-b'),
                 'Admin B', 'admin', now),
            )
            legacy_hash = hashlib.sha256('legacy-password'.encode()).hexdigest()
            db.execute(
                'INSERT INTO users (club_id,email,password,nom,role,cree_le) VALUES (?,?,?,?,?,?)',
                (self.club_a, 'legacy@example.test', legacy_hash, 'Legacy', 'admin', now),
            )
            db.commit()

    def authenticate(self, client, club_id, role='admin'):
        with client.session_transaction() as sess:
            sess.update({
                'club_id': club_id,
                'club_nom': f'Club {club_id}',
                'club_slug': f'club-{club_id}',
                'user_id': club_id,
                'user_nom': 'Test',
                'user_role': role,
                'nb_terrains': 2,
                '_csrf_token': f'csrf-{club_id}',
            })
        return {'X-CSRF-Token': f'csrf-{club_id}'}

    def insert_tournament(self, club_id, name):
        with jap_app.get_db() as db:
            cur = db.execute(
                'INSERT INTO tournois (nom,data_json,cree_le,club_id) VALUES (?,?,?,?)',
                (name, json.dumps({'private': name}), 'test', club_id),
            )
            db.commit()
            return cur.lastrowid

    def insert_sms_history(self, club_id):
        with jap_app.get_db() as db:
            cur = db.execute(
                'INSERT INTO sms_history (tournoi_nom,date_envoi,details,club_id) VALUES (?,?,?,?)',
                ('Tournoi privé', 'test', json.dumps([{'tel': '0600000000'}]), club_id),
            )
            db.commit()
            return cur.lastrowid

    @staticmethod
    def csv_for_pairs(count):
        header = (
            'Epreuve;Equipe;Num;Nom J1;Prenom J1;Age J1;Lic J1;Clt J1;Nat J1;Ent J1;Tel J1;'
            'Nom J2;Prenom J2;Age J2;Lic J2;Clt J2;Nat J2;Ent J2;Tel J2;Poids'
        )
        rows = [header]
        for index in range(1, count + 1):
            rows.append(
                f';P{index};;N{index}A;P{index}A;;L{index}A;;;;0611111111;'
                f'N{index}B;P{index}B;;L{index}B;;;;0622222222;{index * 10}'
            )
        return '\n'.join(rows)

    def guided_payload(self, count, **overrides):
        payload = {
            'csv': self.csv_for_pairs(count),
            'nbPistes': 2,
            'niveau': 'P100',
            'epreuve': 'Messieurs',
        }
        payload.update(overrides)
        return payload

    def test_private_tournament_routes_require_authentication(self):
        client = jap_app.app.test_client()
        self.assertEqual(client.get('/tournoi/liste').status_code, 401)
        self.assertEqual(client.get('/tournoi/charger/1').status_code, 401)
        self.assertEqual(client.delete('/tournoi/supprimer/1').status_code, 401)

    def test_authenticated_generation_still_works_with_csrf_protection(self):
        client = jap_app.app.test_client()
        headers = self.authenticate(client, self.club_a)

        response = client.post(
            '/generer',
            json=self.guided_payload(8),
            headers=headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.get_json()['paires']), 8)

    def test_main_page_contains_csrf_token_and_no_twilio_secret_fields(self):
        client = jap_app.app.test_client()
        self.authenticate(client, self.club_a)

        response = client.get('/')
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('meta name="csrf-token"', body)
        self.assertIn('id="epreuve"', body)
        self.assertIn('<option value="P50">P50</option>', body)
        self.assertNotIn('id="tw-tok"', body)
        self.assertNotIn("localStorage.setItem('tw_tok'", body)

    def test_tournament_list_is_scoped_to_current_club(self):
        own_id = self.insert_tournament(self.club_a, 'Tournoi A')
        self.insert_tournament(self.club_b, 'Tournoi B')
        client = jap_app.app.test_client()
        self.authenticate(client, self.club_a)

        response = client.get('/tournoi/liste')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [{
            'id': own_id,
            'nom': 'Tournoi A',
            'date_str': None,
            'nb_paires': None,
            'niveau': None,
            'cree_le': 'test',
        }])

    def test_cross_club_load_update_and_delete_are_blocked(self):
        other_id = self.insert_tournament(self.club_b, 'Tournoi B')
        client = jap_app.app.test_client()
        headers = self.authenticate(client, self.club_a)

        self.assertEqual(client.get(f'/tournoi/charger/{other_id}').status_code, 404)
        self.assertEqual(client.post(
            '/tournoi/sauvegarder',
            json={'tournoiId': other_id, 'nom': 'Piraté'},
            headers=headers,
        ).status_code, 404)
        self.assertEqual(
            client.delete(f'/tournoi/supprimer/{other_id}', headers=headers).status_code,
            404,
        )

    def test_new_tournament_is_owned_by_current_club(self):
        client = jap_app.app.test_client()
        headers = self.authenticate(client, self.club_b)

        response = client.post(
            '/tournoi/sauvegarder',
            json={'nom': 'Créé par B', 'genData': {}},
            headers=headers,
        )

        self.assertEqual(response.status_code, 200)
        with jap_app.get_db() as db:
            row = db.execute(
                'SELECT club_id FROM tournois WHERE id=?',
                (response.get_json()['id'],),
            ).fetchone()
        self.assertEqual(row['club_id'], self.club_b)

    def test_sms_history_is_scoped_to_current_club(self):
        history_id = self.insert_sms_history(self.club_b)
        client = jap_app.app.test_client()
        headers = self.authenticate(client, self.club_a)

        self.assertEqual(client.get(f'/sms/historique/detail/{history_id}').status_code, 404)
        self.assertEqual(
            client.delete(f'/sms/historique/supprimer/{history_id}', headers=headers).status_code,
            404,
        )

    def test_csrf_token_is_required_for_mutations(self):
        own_id = self.insert_tournament(self.club_a, 'Tournoi A')
        client = jap_app.app.test_client()
        self.authenticate(client, self.club_a)

        response = client.delete(f'/tournoi/supprimer/{own_id}')

        self.assertEqual(response.status_code, 403)
        self.assertTrue(response.get_json()['error'].startswith('Requete de securite invalide'))

    def test_legacy_password_is_migrated_after_successful_login(self):
        client = jap_app.app.test_client()

        response = client.post('/login', json={
            'email': 'legacy@example.test',
            'password': 'legacy-password',
        })

        self.assertEqual(response.status_code, 200)
        with jap_app.get_db() as db:
            stored = db.execute(
                "SELECT password FROM users WHERE email='legacy@example.test'"
            ).fetchone()['password']
        self.assertNotEqual(stored, hashlib.sha256('legacy-password'.encode()).hexdigest())
        self.assertTrue(check_password_hash(stored, 'legacy-password'))

    def test_login_is_temporarily_locked_after_repeated_failures(self):
        client = jap_app.app.test_client()
        payload = {'email': 'a@example.test', 'password': 'wrong-password'}

        for _ in range(5):
            self.assertEqual(client.post('/login', json=payload).status_code, 401)

        response = client.post('/login', json=payload)
        self.assertEqual(response.status_code, 429)

    def test_sms_uses_server_credentials_not_browser_credentials(self):
        with jap_app.get_db() as db:
            db.execute(
                "UPDATE clubs SET twilio_sid='server-sid', twilio_token='server-token', "
                "twilio_num='+33900000000' WHERE id=?",
                (self.club_a,),
            )
            db.commit()
        client = jap_app.app.test_client()
        headers = self.authenticate(client, self.club_a)

        with patch('twilio.rest.Client') as client_class:
            client_class.return_value.messages.create.return_value.sid = 'message-sid'
            response = client.post(
                '/sms/envoyer',
                json={
                    'messages': [{'tel': '0611111111', 'telClean': '33611111111', 'msg': 'Test'}],
                    'twilioSid': 'browser-sid',
                    'twilioToken': 'browser-token',
                    'twilioFrom': '+33800000000',
                },
                headers=headers,
            )

        self.assertEqual(response.status_code, 200)
        client_class.assert_called_once_with('server-sid', 'server-token')
        send = client_class.return_value.messages.create
        self.assertEqual(send.call_args.kwargs['from_'], '+33900000000')

    def test_session_reports_messaging_status_without_exposing_credentials(self):
        with jap_app.get_db() as db:
            db.execute(
                "UPDATE clubs SET twilio_sid='sid-secret', twilio_token='token-secret', "
                "twilio_num='number-secret' WHERE id=?",
                (self.club_a,),
            )
            db.commit()
        client = jap_app.app.test_client()
        self.authenticate(client, self.club_a)

        response = client.get('/api/session')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['sms_configured'])
        self.assertTrue(response.get_json()['whatsapp_configured'])
        payload = json.dumps(response.get_json())
        self.assertNotIn('sid-secret', payload)
        self.assertNotIn('token-secret', payload)
        self.assertNotIn('number-secret', payload)

    def test_admin_api_does_not_expose_twilio_credentials(self):
        with jap_app.get_db() as db:
            db.execute(
                "UPDATE clubs SET twilio_sid='sid-secret', twilio_token='token-secret', "
                "twilio_num='number-secret' WHERE id=?",
                (self.club_a,),
            )
            db.commit()
        client = jap_app.app.test_client()
        self.authenticate(client, self.club_a, role='superadmin')

        response = client.get('/admin/clubs/liste')

        self.assertEqual(response.status_code, 200)
        payload = json.dumps(response.get_json())
        self.assertNotIn('sid-secret', payload)
        self.assertNotIn('token-secret', payload)
        self.assertNotIn('number-secret', payload)

    def test_twilio_webhook_rejects_unsigned_requests(self):
        client = jap_app.app.test_client()

        response = client.post('/sms/reponse', data={
            'From': '+33600000000',
            'Body': 'Message test',
        })

        self.assertEqual(response.status_code, 403)

    def test_pool_planning_never_uses_more_courts_than_available(self):
        pairs = [
            {'id': index, 'nc': f'Paire {index}'}
            for index in range(1, 10)
        ]
        pools = [pairs[0:3], pairs[3:6], pairs[6:9]]

        planning = jap_app.calc_planning_poules(pools, '09:00', 30, 2)

        self.assertEqual([item['terrain'] for item in planning], [1, 2, 1])
        self.assertEqual(planning[2]['matchs'][0]['heure'], '10:30')
        self.assertLessEqual(max(item['terrain'] for item in planning), 2)

    def test_pool_route_respects_phase_one_court_count(self):
        client = jap_app.app.test_client()
        headers = self.authenticate(client, self.club_a)

        response = client.post(
            '/generer-poules',
            json={
                'csv': self.csv_for_pairs(9),
                'nbPoules': 3,
                'nbPistes': 1,
                'nbPistesPhase2': 1,
                'nbQualifies': 2,
                'dureeMatch': 30,
                'heureDebut': '09:00',
            },
            headers=headers,
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data['nbPistes'], 1)
        self.assertTrue(all(pool['terrain'] == 1 for pool in data['planning']))
        self.assertEqual([pool['matchs'][0]['heure'] for pool in data['planning']],
                         ['09:00', '10:30', '12:00'])

    def test_pool_pdf_is_generated_with_phase_two_matches(self):
        client = jap_app.app.test_client()
        headers = self.authenticate(client, self.club_a)
        generated = client.post(
            '/generer-poules',
            json={
                'csv': self.csv_for_pairs(8),
                'nbPoules': 2,
                'nbPistes': 2,
                'nbPistesPhase2': 2,
                'nbQualifies': 2,
                'dureeMatch': 30,
            },
            headers=headers,
        )
        self.assertEqual(generated.status_code, 200)

        response = client.post('/pdf/poules', json=generated.get_json(), headers=headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'application/pdf')
        self.assertTrue(response.data.startswith(b'%PDF'))

    def test_fixed_table_rejects_more_than_twelve_pairs(self):
        client = jap_app.app.test_client()
        headers = self.authenticate(client, self.club_a)

        response = client.post(
            '/generer',
            json=self.guided_payload(13),
            headers=headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('8 ou 12 paires', response.get_json()['error'])

    def test_fixed_table_rejects_unimplemented_intermediate_size(self):
        client = jap_app.app.test_client()
        headers = self.authenticate(client, self.club_a)

        response = client.post(
            '/generer',
            json=self.guided_payload(10),
            headers=headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('8 ou 12 paires', response.get_json()['error'])

    def test_three_match_template_rejects_formats_e_and_f(self):
        client = jap_app.app.test_client()
        headers = self.authenticate(client, self.club_a)

        response = client.post(
            '/generer',
            json=self.guided_payload(8, formatJeu='F : 1 set 4 jeux'),
            headers=headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('au moins 5 matchs', response.get_json()['error'])

    def test_three_match_schedule_rejects_e_or_f_for_classification(self):
        client = jap_app.app.test_client()
        headers = self.authenticate(client, self.club_a)

        response = client.post(
            '/generer',
            json=self.guided_payload(
                8,
                formatJeu='D2 : 1 set 9 jeux',
                formatJeuClassement='F : 1 set 4 jeux',
            ),
            headers=headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('planning à 3 matchs', response.get_json()['error'])

    def test_validation_errors_block_fixed_table_generation(self):
        client = jap_app.app.test_client()
        headers = self.authenticate(client, self.club_a)
        duplicate_csv = self.csv_for_pairs(8).replace('L8A', 'L1A')

        response = client.post(
            '/generer',
            json=self.guided_payload(8, csv=duplicate_csv),
            headers=headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('Doublon de licence', response.get_json()['error'])

    def test_p250_mens_event_requires_twelve_pairs(self):
        client = jap_app.app.test_client()
        headers = self.authenticate(client, self.club_a)

        response = client.post(
            '/generer',
            json=self.guided_payload(8, niveau='P250', epreuve='Messieurs'),
            headers=headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('minimum FFT 12 paires', response.get_json()['error'])

    def test_p250_womens_event_accepts_eight_pair_template(self):
        client = jap_app.app.test_client()
        headers = self.authenticate(client, self.club_a)

        response = client.post(
            '/generer',
            json=self.guided_payload(8, niveau='P250', epreuve='Dames'),
            headers=headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['niveau'], 'P250')
        self.assertEqual(response.get_json()['epreuve'], 'Dames')

    def test_guided_mode_rejects_levels_not_yet_covered(self):
        client = jap_app.app.test_client()
        headers = self.authenticate(client, self.club_a)

        response = client.post(
            '/generer',
            json=self.guided_payload(8, niveau='P500'),
            headers=headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('de P25 à P250', response.get_json()['error'])

    def test_guided_mode_requires_explicit_event_configuration(self):
        client = jap_app.app.test_client()
        headers = self.authenticate(client, self.club_a)

        response = client.post(
            '/generer',
            json={'csv': self.csv_for_pairs(8), 'nbPistes': 2},
            headers=headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('niveau et le type d’épreuve', response.get_json()['error'])


if __name__ == '__main__':
    unittest.main()
