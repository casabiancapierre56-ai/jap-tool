# Référentiel FFT utilisé par JAP Tool

Référentiel vérifié le 11 septembre 2026 pour l'année sportive 2027 :

- [Guide de la compétition Padel — Chapitre I, règles générales](https://fft-site.cdn.prismic.io/fft-site/D00_YbhPgWC-DPTj_CHAPITREI-Re%CC%80glesGe%CC%81ne%CC%81rales-2027.pdf)
- [Guide de la compétition Padel — Chapitre III, cahiers des charges](https://fft-site.cdn.prismic.io/fft-site/tNMM-jlQXVDb9Po1_CHAPITREIIICahierdeschargesdestournois2027.pdf)

## Règles déjà contrôlées par l'application

- Le niveau (P25, P50, P100 ou P250) et le type d'épreuve (Dames,
  Messieurs ou Mixtes) sont choisis explicitement.
- Les minima de paires du cahier des charges 2027 sont contrôlés :

  | Niveau | Dames | Messieurs | Mixtes |
  | --- | ---: | ---: | ---: |
  | P25 | 4 | 4 | 4 |
  | P50 | 4 | 4 | 4 |
  | P100 | 4 | 8 | 8 |
  | P250 | 4 | 12 | 12 |

- Les paires importées sont ordonnées par poids.
- Les doublons de licence bloquent la génération du TMC guidé.
- Le TMC guidé propose trois matchs par paire et refuse donc les formats E et F,
  tant pour le tableau principal que pour les matchs de classement. La FFT exige
  au moins cinq matchs proposés par paire pour un tournoi aux formats E/F et les
  interdit lorsqu'un joueur dispute trois matchs dans la journée.
- Les poules sont réparties en serpentin, avec une tête de série par poule.
- Le planning des poules ne peut pas utiliser plus de pistes que le nombre configuré.

## Limite fonctionnelle actuelle

Le modèle TMC guidé est fiabilisé uniquement pour 8 ou 12 paires. Cette limite est
technique et ne constitue pas une règle FFT. Les autres effectifs doivent rester
identifiés comme « tableau libre » tant que leur structure et leurs matchs de
classement n'ont pas été validés automatiquement.

Les scores et résultats ne sont pas gérés par JAP Tool : ils restent saisis dans
MOJA. Le périmètre de JAP Tool est la préparation du tableau, des convocations et
des documents du jour J.
