# Dataset de muestra

Mismo formato que el dataset real, con otras personas y mucho menos volumen. `input/` tiene las tres fuentes tal como las entrega la API; `expected_output/` es una salida ideal completa, incluido `entities.json`. `tests_sample.json` son los tests que esa salida pasa.

Úsalo para entender el formato de salida y lo que mide cada familia de test. El validador se corre así:

    reto-run validate expected_output/ --public .
