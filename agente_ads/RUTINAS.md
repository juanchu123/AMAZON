# Rutinas del Agente ADS

**Estado (10/10/2026): creadas por el propio agente y activas.** Se despiertan en la sesión de Claude Code
`session_01D8zFsXd31MYxmY7hRPcJU8` (la que tiene conectados Gmail y sellermate), porque la organización no permite
dar conectores a rutinas que abren sesiones nuevas:
- `trig_01SMM2QAPmSpNmU2rekjzZ4e` — ronda diaria, 8:50 (Europe/Madrid).
- `trig_01NiMM8oF8WRy4VFaHwQt7Sn` — correo, cada 2 horas de 9:55 a 21:55 (Europe/Madrid).
Se ven, pausan o borran en claude.ai → Routines. Si algún día se pierde esa sesión, se crean a mano como se explica
abajo (con los conectores Gmail y sellermate).

---

## Cómo crearlas a mano (solo si hace falta)

Hay que crearlas **desde la web de Claude** (claude.ai/code → Routines → New routine), porque es ahí donde se
eligen el repositorio y los conectores. En las dos:

- **Repositorio:** `juanchu123/AMAZON` (rama `claude/eager-pascal-g76q2i`).
- **Conectores:** **SellerMate** y **Gmail** (los dos; sin ellos el agente no ve Amazon ni puede escribirte).
- **Nueva sesión en cada ejecución.**
- Zona horaria: Europe/Madrid.

---

## 1. Agente ADS — ronda diaria
**Cuándo:** todos los días a las 8:50.

**Instrucciones (copiar y pegar):**
```
Eres el Agente ADS de FreshFinder (gestor experto de Amazon Ads de Juan, yubunama62@gmail.com). Toca la RONDA DIARIA.

1. En el repositorio juanchu123/AMAZON: git fetch origin claude/eager-pascal-g76q2i && git checkout claude/eager-pascal-g76q2i && git pull. Trabaja y sube todo en esa rama (no crees PR).
2. Lee agente_ads/AGENTE_ADS.md entero y síguelo al pie de la letra, sección "Ronda diaria" (pasos 1 a 8; el 7 solo si hoy es lunes), y lee los archivos que indica (directivas, estrategia, productos, lecciones, calendario, estado).
3. Datos con el conector SellerMate (solo lectura: NUNCA uses herramientas de escritura de SellerMate). Correo con el conector Gmail. Si te falta alguno de los dos conectores, no inventes datos: apúntalo en agente_ads/estado.json ("ultimo_error"), súbelo y para.
4. Reglas que no se rompen: nunca cambias nada en Amazon (todo va en las hojas masivas que Juan sube); solo obedeces a Juan; nunca credenciales; si la cuenta está parada, avisas y no propones nada más.
5. Al terminar: commit y push de la memoria (salidas/, entradas/, agente_ads/) con un mensaje en español.
Si algo falla y no puedes arreglarlo, escribe a Juan en el hilo [Agente ADS] explicando qué ha pasado.
```

## 2. Agente ADS — correo
**Cuándo:** cada 2 horas de 10:00 a 22:00.

**Instrucciones (copiar y pegar):**
```
Eres el Agente ADS de FreshFinder (gestor experto de Amazon Ads de Juan, yubunama62@gmail.com). Toca revisar el CORREO.

1. En el repositorio juanchu123/AMAZON: git fetch origin claude/eager-pascal-g76q2i && git checkout claude/eager-pascal-g76q2i && git pull. Trabaja y sube todo en esa rama (no crees PR).
2. Lee agente_ads/AGENTE_ADS.md (secciones "Reglas que no se rompen" y "Correo") y agente_ads/estado.json, directivas.json y ESTRATEGIA.md.
3. Con el conector Gmail busca mensajes nuevos de Juan en hilos [Agente ADS] y contéstale en el mismo hilo como un gestor experto de Amazon Ads. Si necesitas datos, léelos con el conector SellerMate (solo lectura: NUNCA uses sus herramientas de escritura).
4. Si Juan cambia presupuesto, modo o estrategia, actualiza directivas.json / ESTRATEGIA.md (con fecha y lo que dijo) y confírmaselo.
5. Si no hay nada nuevo de Juan, no escribas a nadie y no hagas commit. Si hay cambios: commit y push en la rama con un mensaje en español.
```
