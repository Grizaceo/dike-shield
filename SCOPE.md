# Alcance

La idea salió de un torneo de ideación (KISS Discovery Engine + Mercury 3) en el que dos jueces
Mercury evaluaron 728 ideas y Devin participó como co-juez. El artefacto completo es local y no se
versiona; aquí queda solo lo que el implementador necesita.

## Lo que entra

| Pieza | Origen en el torneo | Por qué |
|---|---|---|
| Escenario principal: demanda por despido (Código del Trabajo y leyes laborales) | Idea ganadora n.º 1, "Diké Laboral" | Usuario y documento concretos, alto costo de error y el dominio mejor cubierto por el corpus |
| Arquitectura del escudo: borrador → extractor → Diké → juez → reparar, retirar, abstenerse o escalar | Idea n.º 2, "Diké Shield" | Es el único diseño en que Nemotron es generador, juez y sujeto medido; acepta preguntas arbitrarias del jurado, así que no hay ruta hardcodeada |
| Abstención razonada cuando el corpus no alcanza | Idea "preguntas gemelas" | Encarna la tesis de Diké; la demo es barata y memorable |
| Banco adversarial con métricas por lane, sin escudo y con escudo | Idea "Caza-hormigas" | Convierte el pitch del premio Nemotron en una cifra medida |
| Segundo escenario: finiquito | Idea n.º 4 | Muestra que el sistema no es una ruta única |
| Modo "auditar texto pegado" (un borrador propio o de la contraparte) | Idea "Cita fantasma" | Reutiliza el mismo pipeline sin agregar arquitectura |
| Meterless: H-MEM (citas refutadas y trampas entre sesiones) y Markovian (loop acotado) | Requisito del hackathon | Basta un engine; H-MEM es el obligatorio para nosotros y Markovian el segundo |
| Zetaris como capa de datos: corpus, trazas, memoria espejo y banco en Postgres, consultados vía Zetaris | Requisito del hackathon | Una sola vía SQL para el agente y los dashboards |
| Commitment firmado de las citas verificadas en cada respuesta final | Fortaleza previa de Diké | El jurado puede comprobarlo offline |

## Lo que queda fuera, y por qué

| Fuera | Por qué |
|---|---|
| Redactar escritos completos | Diké prueba citas, no argumentos. Generar un escrito entero sobrepromete y no cabe en 4 días |
| Parsear PDF o DOCX | El parseo de documentos reales (encabezados, notas, OCR) consume días. La entrada es texto pegado o `.md` |
| Áreas no cubiertas por el corpus (municipal, compras públicas, transparencia, fintech, tránsito) | Sin la norma en el corpus, Diké solo puede rechazar. Descargar normas nuevas requiere autorización del autor |
| Consultar la API de Ley Chile en vivo | Mismo motivo. Queda una opción de Zetaris (registrarla como tabla REST) apagada por defecto (`ZETARIS_ENABLE_BCN=false`) |
| Certificar el mérito sustantivo (por ejemplo, si una cláusula es abusiva) | El juez Nemotron puede opinar, pero la UI lo etiqueta como opinión del modelo, nunca como prueba |
| Datos reales de personas o casos | Solo datos sintéticos o anonimizados, por política del autor y por las reglas del hackathon |
| Scraping judicial | Política vigente del autor |
| Autenticación, multiusuario y despliegue en la nube | Es una demo local y reproducible |
| World Model y Scout Intent como engines integrados | Opcionales. El router de abstención se implementa con reglas y Nemotron, sin afirmar que es Scout Intent |
| Entrenar o ajustar modelos | Fuera de la ventana y de la rúbrica |

## Ajustables

Son propuestas derivadas; se pueden cambiar sin romper el contrato.
- UI estática HTML/JS servida por FastAPI, sin build.
- Tamaño del banco: 30 preguntas (cuanto más grande, más tokens y más tiempo).
- Puertos: API 8780, sidecar de engines 8790, Postgres 55432.
- Identificadores de código en inglés; textos de la UI en español; README, deck y video en inglés para el jurado.
