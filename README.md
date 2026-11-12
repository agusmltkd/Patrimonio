# Patrimonio

PWA personal para controlar cuentas, bolsas de ahorro (operativo, emergencia, casa, largo plazo), el objetivo de compra de vivienda, la hipoteca estimada, la proyección del ahorro y los ingresos extra.

- Un solo `index.html` con todo el código; los datos se guardan en `localStorage` (clave `patrimonio.v1`).
- `sw.js` permite usarla sin conexión.
- Copia de seguridad: Ajustes → Exportar / Importar JSON.

Estimaciones orientativas, no asesoramiento financiero.

## Precios de los fondos

La Action `Actualizar valores liquidativos` (`.github/workflows/navs.yml`) se ejecuta cada día laborable y guarda en `navs.json` el valor liquidativo de los fondos de `funds.json` (fuente principal Morningstar, respaldo Financial Times). La app lo lee al abrirse y calcula el saldo con las participaciones de cada fondo.

Para seguir un fondo nuevo, añade su ISIN a `funds.json` y ponlo también en la cuenta dentro de la app.
