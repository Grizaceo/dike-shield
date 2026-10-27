# CURSOR_LOG — registro de sesiones en Cursor

Requisito del Open Agent Hackathon 2026: cada bloque de trabajo en Cursor se anota aquí con
fecha, modelo, tarea, resultado y evidencia (comando y salida). Sin secretos.

---

## 2026-10-22 — Composer — evidencia local: hello.py

| Campo | Valor |
|---|---|
| Fecha | 2026-10-22T01:20:58-03:00 |
| Host | `omarchy` (local; jar JDBC presente) |
| Modelo | Composer |
| Fase | Config previa |
| Tarea | Crear y ejecutar `/tmp/cursor-check/hello.py` como evidencia de Cursor en local |
| Archivos | `/tmp/cursor-check/hello.py` (fuera del repo) |
| Resultado | PASS |

**Comando y salida:**

```text
$ mkdir -p /tmp/cursor-check && printf '%s\n' 'print("hello")' > /tmp/cursor-check/hello.py && python /tmp/cursor-check/hello.py
hello
```

---

## 2026-10-22 — Composer — JDBC Zetaris ya verificado (reconfirmado)

| Campo | Valor |
|---|---|
| Fecha | 2026-10-22T01:22:30-03:00 |
| Host | `omarchy` |
| Modelo | Composer |
| Fase | Config previa / fase 0 |
| Tarea | Reconfirmar `SELECT 1` y `SHOW LIGHTNING DATABASES` vía JDBC (CLI Cursor → scripts de getting-started); sin imprimir credenciales |
| Archivos | ninguno del repo (usa `~/zetaris-getting-started` + jar en `~/zetaris-platform/jdbc/`) |
| Resultado | PASS (JDBC); REST API key aún pendiente |

**Comando y salida (resumen, sin secretos):**

```text
$ .venv/bin/python scripts/preflight.py --jdbc --jar "$HOME/zetaris-platform/jdbc/ndp-jdbc-driver-2.4.3.1-7eff043-driver.jar"
[PASS] JDBC port 10000: open
[PASS] Java (JDK 11+): ...
[PASS] jaydebeapi: importable
[PASS] driver JAR: .../ndp-jdbc-driver-2.4.3.1-7eff043-driver.jar
[PASS] JDBC SELECT 1
[INFO] lightning databases: NY_TAXI, TPCDS_DB
NOT READY: 2 check(s) failed   # solo ZETARIS_API_KEY / REST — esperado hasta que Cristóbal cree la key
```

**Nota:** la UI de Zetaris responde en http://localhost:3000; REST en `127.0.0.1:8888` (HTTP 404 en la raíz = vivo). Contenedores sanos: `zetaris-ui-1`, `zetaris-api-1`, `zetaris-driver-1`, `zetaris-postgres-1`.

---

## 2026-10-22 — Composer — Zetaris API key + SELECT 1 REST

| Campo | Valor |
|---|---|
| Fecha | 2026-10-22T01:44-03:00 |
| Modelo | Composer |
| Fase | Config previa |
| Tarea | Resolver HTTP 400 al crear token; dejar key en `.env`; verificar `SELECT 1` por REST |
| Archivos | `.env` (solo `ZETARIS_API_KEY`, no versionado); `docs/CURSOR_LOG.md` |
| Resultado | PASS |

**Causa del 400:** nombre con acento (`Diké`) / fecha manual; con nombre ASCII `dike-shield` y caducidad `+ 30 d` el create devolvió 200.

**Evidencia REST (sin secretos):**

```text
POST $ZETARIS_REST_URL/sql-editor/sqls/run  (Bearer, X-Org-ID: 1, X-Request-ID uuid)
HTTP_200
result=[["1"]]
SELECT_1_REST_OK
```

Nota: `wl-copy` al portapapeles del host falló (timeout); la key quedó en `.env` modo 600.

---

## 2026-10-22 — Auto (Cursor CLI, Local) — diagnóstico host/VM; Zetaris no se tocó

| Campo | Valor |
|---|---|
| Fecha | 2026-10-22T02:21-03:00 |
| Host | `omarchy` (local; jar JDBC `ndp-jdbc-driver-2.4.3.1-7eff043-driver.jar` presente) |
| Modelo | Auto / Cursor CLI |
| Fase | Config previa (host libvirt + Meterless); Zetaris ya OK |
| Tarea | Ejecutar `PROMPT_CLI_HOST_VM.md` hasta el punto que requiere sudo de Cristóbal |
| Archivos | `docs/CURSOR_LOG.md`; `.hackathon/PROMPT_SIGUIENTE_SESION.md` |
| Resultado | Diagnóstico PASS; host/VM pendientes de Cristóbal |

**Confirmación Local:** `hostname=omarchy`; cwd `dike-shield`; JDBC jar 31M.

**`04_check.sh` al inicio (Zetaris no rehizo):**

```text
Cursor: [OK] app; [OK] CLI
Zetaris: [OK] bundle; [OK] 4 contenedores; [OK] REST HTTP 404
.env: [OK] ZETARIS_API_KEY
      [FALTA] METERLESS_BASE_URL / RUNTIME_TOKEN / MODEL_FAST / MODEL_DEEP (iguales a .env.example, con <placeholders>)
Nightshift: [FALTA] URL y token del Runtime
Host: RAM available 8 GB (meta 12+); [FALTA] libvirtd
```

**Host medido (sin sudo):**

```text
systemctl is-active libvirtd → inactive (disabled)
groups → gris96 vboxusers wireshark nordvpn wheel   # sin libvirt
virsh net-list --all → tabla vacía
kvm_amd + kvm cargados; también vboxdrv/vboxnet* (ninguna VM VirtualBox running)
paquetes: libvirt y edk2-ovmf sí; virt-manager, dnsmasq, swtpm no
/usr/share/libvirt/networks/default.xml → ausente
/etc/libvirt/qemu/networks/default.xml → existe (root, 0600)
ISO Win11 Enterprise eval ya en ~/Downloads/ (8.2G, 26H2 CLIENTENTERPRISEEVAL)
03_ram.sh: langfuse/opengym/ghostdesk/l4d2 ya stopped; no libera más
RAM: Mem 27G, used 18G, available 8G; Swap used 12G
Top RSS: hermes ~1.2G, blender --background (MCP) ~0.9G, zen-bin ~0.9G + varios Isolated
Contenedores vivos: zetaris-* (healthy) + homeassistant; no se tocan zetaris-*
```

**Parada:** `02_vm_host.sh` pide sudo; el agente no lo corre. Siguiente: Cristóbal ejecuta el script, cierra sesión y vuelve; entonces verificar `libvirtd` / `groups | grep libvirt` / `virsh net-list --all`.

---

## 2026-10-22 — Auto (Cursor CLI, Local) — revisión paso 1 (`02_vm_host.sh`)

| Campo | Valor |
|---|---|
| Fecha | 2026-10-22T02:27-03:00 |
| Host | `omarchy` |
| Modelo | Auto / Cursor CLI |
| Fase | Config previa / host libvirt |
| Tarea | Verificar que Cristóbal corrió `.hackathon/setup/02_vm_host.sh` |
| Archivos | `docs/CURSOR_LOG.md`; `.hackathon/PROMPT_SIGUIENTE_SESION.md` |
| Resultado | PARCIAL: daemon y red OK; grupo `libvirt` en `/etc/group` pero sesión gráfica aún sin el grupo |

**Evidencia (sin secretos):**

```text
systemctl is-active libvirtd  → active
systemctl is-enabled libvirtd → enabled
/etc/group libvirt            → gris96 está en el grupo
groups (esta sesión)          → gris96 vboxusers wireshark nordvpn wheel  # sin libvirt
loginctl session Timestamp    → 2026-10-21 16:33:40 (sesión gráfica ~9 h, no hubo relogin)
virsh uri                     → qemu:///session
virsh net-list --all          → vacío (URI de sesión)
virsh -c qemu:///system net-list --all
  default   active   yes   yes
virsh -c qemu:///system list --all → ninguna VM
paquetes: virt-manager 5.1.0-4, libvirt, dnsmasq, swtpm, edk2-ovmf, qemu-system-x86
faltante recomendado: qemu-desktop (UI spice/gtk del hypervisor)
/dev/kvm crw-rw-rw-
04_check.sh Host: [OK] libvirtd activo; RAM available 8 GB
04_check.sh Meterless: sigue [FALTA]
```

**Siguiente:** Cristóbal cierra la sesión gráfica de verdad (no solo una terminal) y vuelve a entrar; opcional `omarchy pkg add qemu-desktop`. Luego abrir virt-manager y crear la VM Nightshift.

---

## 2026-10-22 — Auto (Cursor CLI, Local) — relogin hecho; `groups` vacío es esperado

| Campo | Valor |
|---|---|
| Fecha | 2026-10-22T03:00-03:00 |
| Host | `omarchy` |
| Modelo | Auto / Cursor CLI |
| Fase | Config previa / host libvirt |
| Tarea | Revisar `groups \| grep libvirt` vacío tras relogin |
| Resultado | Host listo. El grep vacío no bloquea: `Linger=yes` deja grupos viejos en terminales; `/etc/group` ya tiene `libvirt:gris96`; sesión gráfica nueva 34 a las 02:57; `virsh -c qemu:///system` ve red `default` active |

**Atajo:** no insistir en `groups`. Abrir `virt-manager --connect qemu:///system`. Instalar `qemu-desktop` (sudo de Cristóbal).

---

## 2026-10-22 — Auto (Cursor CLI, Local) — VM `win11` creada y running

| Campo | Valor |
|---|---|
| Fecha | 2026-10-22T03:32-03:00 |
| Host | `omarchy` |
| Modelo | Auto / Cursor CLI |
| Fase | Config previa / VM Windows |
| Tarea | Revisar dominio libvirt tras creación en virt-manager |
| Resultado | PASS de receta: 2 vCPU, 4 GiB, Windows 11, UEFI+Secure Boot, TPM 2.0 CRB emulado, red `default`, ISO eval adjunta |

```text
virsh -c qemu:///system list --all
 Id 2  win11  running
CPU(s) 2; Max memory 4194304 KiB
os firmware=efi OVMF_CODE.secboot.4m.fd secure-boot=yes
tpm-crb emulator 2.0
interface network=default (virbr0) model=e1000e
disk qcow2 /var/lib/libvirt/images/win11.qcow2 (~69G en disco; 64 GiB típico)
cdrom ISO CLIENTENTERPRISEEVAL 26H2
libosinfo: http://microsoft.com/win/11
Host RAM available ~9 GB (VM ~4 GB RSS qemu)
```

Siguiente: terminar instalación de Windows 11 + Nightshift; URL/token a `.env`.

---

## 2026-10-22 — Auto (Cursor CLI, Local) — canal nativo QEMU Guest Agent en `win11`

| Campo | Valor |
|---|---|
| Fecha | 2026-10-22T03:38-03:00 |
| Host | `omarchy` |
| Modelo | Auto / Cursor CLI |
| Fase | Config previa / control de VM |
| Tarea | Buscar control nativo (no CUA) y dejar el canal libvirt listo |
| Resultado | Canal `org.qemu.guest_agent.0` attached live+config. `qemu-agent-command guest-ping` aún falla: no hay qemu-ga dentro de Windows. |

Fuentes: wiki.libvirt.org/Qemu_guest_agent.html ; qemu.org interop/qemu-ga-ref ; virtio-win.github.io Knowledge-Base/Qemu-ga-win.html. Wrappers MCP: kvm-mcp, mcp-qemu-vnc, mcqemu (envuelven QMP/QGA/libvirt; no sustituyen instalar el agente en el guest).

---

## 2026-10-27 — Composer — Zetaris arriba + SELECT 1 REST; Langfuse detenido

| Campo | Valor |
|---|---|
| Fecha | 2026-10-27T01:12:01-03:00 |
| Host | `omarchy` |
| Modelo | Composer |
| Fase | 01:20–02:00 estado y Zetaris |
| Tarea | Confirmar estado, liberar RAM (Langfuse), `docker compose up -d` + `verify.sh` 9/9, `SELECT 1` por REST |
| Archivos | `docs/CURSOR_LOG.md` |
| Resultado | PASS Zetaris; Nightshift/Meterless sigue FALTA |

**RAM al inicio (Langfuse se había relanzado solo):** 5 GB available. `docker inspect` previo a reintentar:

```text
zetaris-ui-1        OOMKilled=false Exit=0   FinishedAt=2026-10-27T02:26:45Z
zetaris-api-1       OOMKilled=false Exit=143 FinishedAt=2026-10-27T02:26:46Z
zetaris-driver-1    OOMKilled=false Exit=137 FinishedAt=2026-10-27T02:26:55Z
zetaris-postgres-1  OOMKilled=false Exit=0   FinishedAt=2026-10-27T02:26:45Z
```

Driver 137 no fue OOMKilled de Docker (probable SIGKILL del host). `03_ram.sh stop` (Langfuse/opengym/ghostdesk/l4d2; no toca zetaris ni homeassistant):

```text
Antes: disponible 5 GB
stop: l4d2-wine-v3 langfuse-* (7) opengym-web-1 opengym-api-1 ghostdesk
Después: disponible 8 GB (meta: 12 o más)
```

**Zetaris:**

```text
$ cd ~/zetaris-platform && docker compose up -d && ./verify.sh
zetaris-{postgres,driver,api,ui}-1 healthy; OOMKilled=false
All 9 checks passed. The platform is ready on http://localhost:3000
```

**REST SELECT 1** (Bearer + `X-Org-ID: 1` + `X-Request-ID` uuid; sin imprimir la key):

```text
POST $ZETARIS_REST_URL/sql-editor/sqls/run
HTTP_200
keys=['data', 'headers', 'timeUsed', 'total']
data=[['1']]
SELECT_1_REST_OK=True
```

**Confirmado, no redescubierto:** repo 3 commits (`709eff3`); sin `shield/` `db/` `engines/` `tests/` `scripts/smoke_test.py`; `win11` shut off 2 vCPU / 4 GB; red `default` active+autostart; nada en `:8088`; Meterless en `.env` sigue con placeholders; `libvirtd` active.

**04_check.sh:** Cursor OK; Zetaris 4 contenedores + REST HTTP 404 OK; `ZETARIS_API_KEY` OK; Meterless URL/token/FAST/DEEP FALTA; RAM 8 GB available (meta 12+ con VM).

**Siguiente:** no arrancar `win11` hasta más RAM o ok de Cristóbal (VM pide 4 GB). Nightshift lo instala él dentro de Windows.

---

## 2026-10-27 — Composer — bajar MCP/servicios ociosos para RAM

| Campo | Valor |
|---|---|
| Fecha | 2026-10-27T01:18:00-03:00 |
| Modelo | Composer |
| Fase | 01:20–02:00 RAM para VM |
| Tarea | Detener Meshy, Azure, Blender, VirtualBox MCP, llama, voxtype, OpenCode, Devin. No tocar `next-server` (es `zetaris-ui-1`) |
| Archivos | `docs/CURSOR_LOG.md` (solo log) |
| Resultado | PARCIAL: todos abajo salvo `llama-server`, que Hermes relanza |

```text
systemctl --user stop+disable voxtype.service blender-mcp-bridge.service
SIGTERM: meshy n=8, azure n=3, mcp-virtualbox n=16, blender-mcp n=7, llama, voxtype leftover, opencode, devin
zetaris-* intactos (healthy)
RAM available: 8 GB → 10 GB
llama-server: Hermes pid 1316 lo vuelve a levantar en :8081
```

---

## 2026-10-27 — Composer — Firecrawl, chrome-devtools, Home Assistant down

| Campo | Valor |
|---|---|
| Fecha | 2026-10-27T01:18:55-03:00 |
| Modelo | Composer |
| Fase | 01:20–02:00 RAM para VM |
| Tarea | Bajar MCP Firecrawl, chrome-devtools y contenedor homeassistant |
| Archivos | `docs/CURSOR_LOG.md` |
| Resultado | PASS; RAM llegó a la meta 12 GB; Zetaris intacto |

```text
docker stop homeassistant  → exited
SIGTERM firecrawl + chrome-devtools-mcp  n=26  ~3046 MB
quedan down a +4s
zetaris-* 4 healthy
RAM available 9.8Gi → 12Gi
```

---

## 2026-10-27 — Composer — `win11` running, escritorio OK, sin IP DHCP

| Campo | Valor |
|---|---|
| Fecha | 2026-10-27T01:21:00-03:00 |
| Modelo | Composer |
| Fase | 02:00 Nightshift / VM |
| Tarea | `virsh start win11`; screenshot framebuffer; IP por ARP |
| Archivos | `docs/CURSOR_LOG.md` |
| Resultado | PARCIAL: VM running + escritorio Windows 11 (no OOBE). Sin lease DHCP / sin ARP. Zetaris intacto |

```text
$ virsh -c qemu:///system start win11
Domain 'win11' started
State: running (booted)  2 vCPU  4194304 KiB
SPICE 127.0.0.1:5900
qemu RSS 4129 MB
screenshot 1280x800: desktop Win11 Enterprise Eval (watermark license expired), 1:20 AM 10/27/2026
virsh net-dhcp-leases default  → vacío
domifaddr --source arp         → vacío
ip neigh virbr0                → vacío
zetaris-* healthy oom=false
host RAM available 12Gi → 8.6Gi
:8088 sigue vacío
```

**Bloqueo:** Windows no tomó `192.168.122.x`. Cristóbal abre SPICE y activa Ethernet. Sin IP no hay Nightshift alcanzable desde Linux.

---

## 2026-10-27 — Composer — win11 reportó APIPA `169.254.220.36` (no usable)

| Campo | Valor |
|---|---|
| Fecha | 2026-10-27T01:40:00-03:00 |
| Modelo | Composer |
| Fase | 02:00 Nightshift / red VM |
| Tarea | Interpretar IPv4 que pegó Cristóbal; comprobar si el host llega a la VM |
| Resultado | BLOQUEADO: APIPA; DHCP de libvirt vacío; el ping a 169.254.220.36 **no** va a la VM |

```text
virbr0 192.168.122.1/24 UP; dnsmasq default corriendo; DHCP range 192.168.122.2-254
net-dhcp-leases default → vacío
domifaddr arp → vacío
ip route get 169.254.220.36 → via 192.168.100.1 dev enp7s0 src 192.168.100.149
  (sale por la LAN física, no por virbr0)
```

`169.254.220.36/16` es APIPA: Windows no recibió DHCP. No usar esa IP como `METERLESS_BASE_URL`.
Siguiente: IP estática `192.168.122.50/24` gw `192.168.122.1` dentro de Windows.

---

## 2026-10-27 — Composer — win11 en `192.168.122.50` (L2 OK, firewall drop)

| Campo | Valor |
|---|---|
| Fecha | 2026-10-27T01:55:00-03:00 |
| Modelo | Composer |
| Fase | 02:00 Nightshift / red VM |
| Tarea | Verificar IP estática que reportó Cristóbal |
| Resultado | PASS L2: MAC de win11 = `192.168.122.50`. ICMP/TCP timeout = firewall de Windows. `:8088` aún cerrado |

```text
domifaddr arp: 52:54:00:92:1e:2c → 192.168.122.50 (y APIPA stale)
ip route get 192.168.122.50 → dev virbr0 src 192.168.122.1
ip neigh 192.168.122.50 → REACHABLE
ping 3/2 → 100% loss
tcp 8088/135/445 → TIMEOUT
zetaris-* healthy; RAM available 14Gi
```

Siguiente (solo Cristóbal en Windows): perfil de red Private, instalar Nightshift (edición Windows, no browser), NVIDIA + lanes, firewall TCP 8088, URL/token al `.env`.

---

## 2026-10-27 — Composer — control QEMU (send-key): NAT ICMP OK, DNS UDP bloqueado

| Campo | Valor |
|---|---|
| Fecha | 2026-10-27T02:04:09-03:00 |
| Modelo | Composer |
| Fase | 02:00 Nightshift / red VM |
| Tarea | Controlar win11 con `virsh send-key` + screenshot (sin guest-agent) |
| Resultado | Teclado QEMU OK. Gateway y `1.1.1.1` ping OK. DNS UDP timeout aún con firewall Windows off |

```text
ipconfig: Ethernet 192.168.122.50/24 gw 192.168.122.1
ping 192.168.122.1 → 0% loss
ping 1.1.1.1 → 0% loss 5ms TTL=54   # NAT ICMP funciona
nslookup google.com 1.1.1.1 → timeout
nslookup google.com 192.168.122.1 → timeout  (dnsmasq en el host SÍ responde a dig local)
netsh advfirewall set allprofiles state off → Ok (admin); DNS sigue timeout
Edge meterless.ai: DNS_PROBE_FINISHED_NO_INTERNET
```

Bloqueo: UDP/53 desde la VM no llega a dnsmasq ni a 1.1.1.1. Hace falta `sudo iptables` en el host.

---

## 2026-10-27 — Composer — DNS OK tras iptables; meterless.ai carga en Edge

| Campo | Valor |
|---|---|
| Fecha | 2026-10-27T02:06:00-03:00 |
| Modelo | Composer |
| Fase | 02:00 Nightshift / red VM |
| Tarea | Reprobar DNS tras `sudo iptables` de Cristóbal; fijar DNS 1.1.1.1 |
| Resultado | PASS: nslookup google.com 1.1.1.1 resuelve; Edge carga https://meterless.ai |

```text
nslookup google.com 1.1.1.1 → one.one.one / A records 64.233.186.*
netsh interface ip set dns Ethernet static 1.1.1.1
Edge tab: "Meterless Nightshift"; página con "Try Nightshift free"
```

---

## 2026-10-27 — Composer — Nightshift falla por VCRUNTIME140.dll

| Campo | Valor |
|---|---|
| Fecha | 2026-10-27T02:15:00-03:00 |
| Modelo | Composer |
| Fase | 02:00 Nightshift install |
| Tarea | Reproducir el error del instalador |
| Resultado | `Nightshift-Setup-Windows.exe` pide `VCRUNTIME140.dll` (VC++ Redistributable) |

```text
Downloads: Nightshift-Setup-Windows  644884 KB  (~630 MB)
Error: The code execution cannot proceed because VCRUNTIME140.dll was not found.
vc_redist.x64.exe oficial (26M) servido en http://192.168.122.1:8765/vcredist.exe
```

---

## 2026-10-27 — Composer — win11 se apagó; subida a 8 GB y arranque

| Campo | Valor |
|---|---|
| Fecha | 2026-10-27T02:21:00-03:00 |
| Modelo | Composer |
| Fase | 02:00 Nightshift / RAM VM |
| Tarea | Nightshift pedía 8 GB (había 4). Dominio quedó `shut off`. `setmaxmem 8G` + start |
| Resultado | PASS: win11 running 8 GiB; escritorio OK; Zetaris intacto |

```text
antes: State shut off; qemu ausente; host available 16Gi
virsh setmaxmem/setmem 8G --config
start win11; Max/Used memory 8388608 KiB; SPICE 127.0.0.1:5900
qemu RSS ~8242 MB; host available 9.6Gi
zetaris-* healthy oom=false
screenshot: escritorio Win11 (Start abierto), license valid 50 days
```

---

## 2026-10-27 — Composer — Nightshift instalado, onboarding 1/5; Runtime aún no

| Campo | Valor |
|---|---|
| Fecha | 2026-10-27T02:41:00-03:00 |
| Modelo | Composer |
| Fase | 02:00 Nightshift setup |
| Tarea | Verificar post-instalación |
| Resultado | App abre (v0.6.2, STEP 1 OF 5). `:8088` TIMEOUT. `.env` Meterless sigue placeholder |

```text
win11 running; ARP 192.168.122.50 REACHABLE
tcp 8088 → TIMEOUT (Runtime no publicado aún)
screenshot: Nightshift onboarding "Stop paying for tokens you didn't need."
```

---

## 2026-10-27 — Composer — firewall 8088 + Hotspot LAN; Runtime alcanzable

| Campo | Valor |
|---|---|
| Fecha | 2026-10-27T02:59:00-03:00 |
| Modelo | Composer |
| Fase | 02:00 Nightshift Runtime |
| Tarea | Regla firewall TCP 8088 en PowerShell admin; verificar puerto |
| Resultado | PASS: `192.168.122.50:8088` CONNECT. Hotspot on. Sin `/models` aún (token no está en `.env`) |

```text
netsh advfirewall firewall add rule name=Nightshift dir=in action=allow protocol=TCP localport=8088
show rule: Enabled Yes, In, TCP, LocalPort 8088, Allow
Console: Hotspot mode on · 192.168.122.50
python connect 192.168.122.50:8088 → CONNECT
```

---

## 2026-10-27 — Composer — pin Nemotron Lightning; lanes locales 0/0

| Campo | Valor |
|---|---|
| Fecha | 2026-10-27T03:25:00-03:00 |
| Modelo | Composer |
| Fase | 02:00 Nightshift lanes |
| Tarea | Crear lanes FAST/DEEP Nemotron vía GUI (computer-use / cua-driver / teclado VM) |
| Archivos | `docs/CURSOR_LOG.md` |
| Resultado | PARCIAL: pin cloud Lightning 30B A3B confirmado; Super VL 120B no está en catálogo; panel Lanes 0/0; GET /models 401 token mismatch |

```text
Computer-use Claude MCP: no disponible en esta sesión Cursor
cua-driver click/bring_to_front: foreground_unavailable (plugin Hyprland ausente)
QEMU HID tablet: el cursor se mueve; los botones no activan (spice mouse: client_agent no)
Teclado virsh send-key: sí (Ctrl+K, Ctrl+6, Tab)

Ctrl+K → Pin model → Nemotron 3.5 Lightning 30B A3B (cloud)
toast x2: "Pinned Nemotron 3.5 Lightning 30B A3B - every run uses it until you unpin."

Catálogo Find-the-right-model "nemotron": 14 matches, todos GGUF locales over budget
PIN A MODEL: Lightning 30B (cloud), Ultra 550B, Embed, Bolt
Ctrl+K "super vl": sin PIN A MODEL (Super VL 120B no aparece)

Ctrl+6 Lanes & memory: 0/0 lanes ready; "No lanes configured"
"Cloud routing still works without one."
"+ Add lane" no alcanzable sin clic real (Tab aterrizó en Console)

Console Proof (recibo previo 02:55): default · meterless/auto · Nemotron 3.5 Bolt E4B
GET http://192.168.122.50:8088/v1/models → 401 runtime_token_mismatch
METERLESS_MODEL_FAST/DEEP siguen placeholder
Hotspot on 192.168.122.50; 8088 CONNECT; Zetaris intacto
```

---

## 2026-10-27 — Composer — wizard Add a lane: job picker

| Campo | Valor |
|---|---|
| Fecha | 2026-10-27T03:28:00-03:00 |
| Modelo | Composer |
| Fase | 02:00 Nightshift lanes |
| Tarea | Leer screenshot Add a lane (Pictures) y elegir el job FAST/DEEP |
| Archivos | `~/Pictures/screenshot-2026-10-27_03-28-14.png` |
| Resultado | Wizard en 01 Language / Solve a complex problem. Instrucción: FAST = Write & edit; DEEP = Solve a complex problem; luego Find a model → Nemotron cloud |

```text
Add a lane → What do you want to do?
Language seleccionado; job "Solve a complex problem"
Footer: 2 on this box (1 fit now) · 118 cloud (11 with a key held)
Find a model →
```

---

## 2026-10-27 — Composer — 2/2 lanes Race: Lightning + Ultra

| Campo | Valor |
|---|---|
| Fecha | 2026-10-27T03:34:00-03:00 |
| Modelo | Composer |
| Fase | 02:00 Nightshift lanes |
| Tarea | Revisar filas Race/Vision/Judge tras Add lane (Cristóbal dejó ambos en Race) |
| Archivos | `docs/CURSOR_LOG.md` |
| Resultado | PASS condicional: 2/2 ready, ambos Race, NVIDIA cloud. FAST=Lightning 30B. DEEP=Ultra 550B (Super VL 120B no está). No mover Ultra a Judge. GET /models sigue 401 |

```text
Lanes & memory 2/2
01 Race (2 lanes, ready, CLOUD NVIDIA, nvidia accepted the key):
  nemotron-3-5-lightning-3
    nvidia/nemotron-3.5-lightning-30b-a3b  262k ctx  $6/$8 per 1M
  nemotron-3-ultra-550b-a5
    nvidia/nemotron-3-ultra-550b-a55b  1M ctx  tools/coding/strong/judging
02 Vision 0  03 Judge 0
resident 0% of 2.7 GB (cloud, no local GGUF)
GET /models 401 runtime_token_mismatch
METERLESS_MODEL_FAST/DEEP placeholder
```

---

## 2026-10-27 — Composer — GET /models 200; FAST/DEEP Nemotron en .env

| Campo | Valor |
|---|---|
| Fecha | 2026-10-27T03:43:00-03:00 |
| Modelo | Composer |
| Fase | 02:00 Nightshift / descubrir rutas |
| Tarea | Tras token arreglado: GET /models y escribir FAST/DEEP |
| Archivos | `.env` (solo MODEL_*; modo 600) |
| Resultado | PASS: HTTP 200, 86 modelos. FAST/DEEP = ids NVIDIA cloud de los lanes Race. No meterless/auto |

```text
GET http://192.168.122.50:8088/v1/models → 200, 86 ids
No usar meterless/fast ni meterless/deep: son disposiciones y pueden rutar fuera de Nemotron
  (recibo previo: meterless/auto → Bolt E4B)
METERLESS_MODEL_FAST=nvidia/nemotron-3.5-lightning-30b-a3b
METERLESS_MODEL_DEEP=nvidia/nemotron-3-ultra-550b-a55b
Super VL 120B ausente en catálogo; DEEP = Ultra 550B
Console Connect sigue mostrando default meterless/auto; la app no lo usa
.env mode 600; token no impreso
```

---

## 2026-10-27 — Composer — smoke 5/5 PASS

| Campo | Valor |
|---|---|
| Fecha | 2026-10-27T03:52:00-03:00 |
| Modelo | Composer |
| Fase | 03:00 smoke de elegibilidad |
| Tarea | `scripts/smoke_test.py`: Zetaris UI, SQL, /models, chat FAST, Diké cita conocida |
| Archivos | `scripts/smoke_test.py`, `FUENTES.md`, `.local/dike-home/` (gitignored) |
| Resultado | PASS 5/5. Lightning exige `max_tokens>=256` (con 16 NVIDIA devolvía empty_response). `~/.lexo` mtime 2026-09-22 intacto |

```text
$ python3 scripts/smoke_test.py
PASS zetaris_web HTTP 200
PASS zetaris_sql SELECT 1 -> [['1']]
PASS meterless_models HTTP 200 n=86 nemotron=11 FAST=nvidia/nemotron-3.5-lightning-30b-a3b DEEP=nvidia/nemotron-3-ultra-550b-a55b
PASS meterless_chat_fast HTTP 200 model=nvidia/nemotron-3.5-lightning-30b-a3b chars=4 4209ms
PASS dike_citation veredicto=TODAS_VERIFICADAS estados=['VERIFICADA'] rc=0
5/5 PASS

primer FAST max_tokens=16 → HTTP 502 provider_error empty_response
reintento max_tokens=256 → pong
DEEP Ultra 200 en diagnóstico
dike starter install chile-base en .local/dike-home (HOME aislado)
FUENTES: Markovian conformance, prompts engines.html, red zetaris_default, catálogo Nightshift
```

---

## 2026-10-27 — Composer — shield-db Postgres 16 en zetaris_default

| Campo | Valor |
|---|---|
| Fecha | 2026-10-27T03:54:00-03:00 |
| Modelo | Composer |
| Fase | 04:00 Fase 1 datos |
| Tarea | Levantar `shield-db` (:55432) unido a la red de Zetaris |
| Archivos | `docker-compose.yml`, `db/schema.sql` |
| Resultado | PASS: schema `shield` con 9 tablas; contenedor en `zetaris_default` junto a zetaris-* |

```text
docker compose up -d
pg_isready -U shield -d shield → ready
tables: articulos banco_corridas banco_items citas eventos_traza
        intercepciones refutadas sesiones trampas
network zetaris_default: zetaris-{driver,api,postgres,ui}-1 shield-db
```

---

## 2026-10-27 — Composer — Fase 1: 8544 artículos + adaptador Diké

| Campo | Valor |
|---|---|
| Fecha | 2026-10-27T04:05:00-03:00 |
| Modelo | Composer |
| Fase | 04:00–07:00 Fase 1 datos + Diké |
| Tarea | Instalar corpus aislado, cargar `shield.articulos`, federar en Zetaris, adaptador CLI y tests 2/1/1 |
| Archivos | `pyproject.toml`, `uv.lock`, `scripts/setup_dike.py`, `db/load_corpus.py`, `zetaris/register.sql`, `scripts/register_zetaris.py`, `shield/{env,zetaris,dike_adapter,cuerpos}.py`, `tests/test_dike_adapter.py` |
| Resultado | PASS: 8544 filas `pack_hash=af1422d66d1e6eee` vía Zetaris; pytest 2 passed; `~/.lexo` mtime 2026-09-22 intacto. Plan B Lightning: views, no `REGISTER TABLES` |

```text
uv run python scripts/setup_dike.py
PASS corpus=.../users/shield/starter/chile-base
PASS key=.../demo-content-signing-key.pem created mode=0o600
PASS ~/.lexo unchanged

uv run python db/load_corpus.py
PASS loaded=8544 pack_hash=8544

uv run python scripts/register_zetaris.py
CREATE DATASOURCE DESCRIBE BY → HTTP 400 (no acentos/espacios en esta build)
REGISTER DATASOURCE TABLES FROM shield_pg → 0 tablas (JDBC ve public; contrato está en schema shield)
CREATE DATASOURCE VIEW articulos ... AS SELECT * FROM shield.articulos
SELECT count(*) FROM shield_pg.articulos → [['8544']]
SELECT count(*) FROM shield_pg.articulos WHERE pack_hash='af1422d66d1e6eee' → [['8544']]
SELECT count(*) FROM shield_pg.shield.articulos → Spark REQUIRES_SINGLE_PART_NAMESPACE
SHOW DATASOURCE TABLES shield_pg → 9 views

uv run pytest tests/test_dike_adapter.py -q
..  [100%]
artículo 161 CT VERIFICADA cl.norma.ct:art:0161
artículo 168 CT VERIFICADA cl.norma.ct:art:0168
artículo 60 FALLO AMBIGUOUS
artículo 9999 CT FALLO UNRESOLVABLE

stat ~/.lexo → 2026-09-22 05:23:13 -0300 (sin cambio)
cd vendor/dike && sha256sum -c ../../PREEXISTING.sha256 → 0 FAILED
```

---

## 2026-10-27 — Composer — Fase 2: loop, API y corrida viva Nemotron

| Campo | Valor |
|---|---|
| Fecha | 2026-10-27T04:36:00-03:00 |
| Modelo | Composer |
| Fase | Fase 2 escudo de punta a punta |
| Tarea | llm, router, drafter, extractor, judge, repairer, loop simple, trace, POST answer/audit |
| Archivos | `shield/{llm,db,trace,extractor,engines,articles,loop,api,jsonutil}.py`, `shield/agents/{router,drafter,judge,repairer}.py`, `tests/test_loop.py`, `tests/fakes.py`, `scripts/fase2_live.py`, `pyproject.toml` |
| Resultado | PASS tests 8/8. Live despido: FAST+DEEP Nemotron, borrador con «artículo 14» AMBIGUOUS, final sin esa cita. Live audit: 9999 in / 9999 out, publicar. `GET /healthz` ok (engines false: H-MEM es Fase 3). `~/.lexo` intacto |

```text
uv run pytest -q
........  [100%]
# publicar, reparar (retira 9999), abstener, escalar, coerce-publicar, extractor, adapter 2/1/1

GET /healthz → 200 {ok:true, zetaris:true, meterless:true, dike:true, engines:false, sample_mode:false}
POST /v1/shield/answer (TestClient, LLM fake) → 200 publicar

LIVE pregunta despido (Runtime):
  drafter FAST nvidia/nemotron-3.5-lightning-30b-a3b 26922ms
  dike CON_PROBLEMAS  (artículo 159 VERIFICADA + artículo 14 AMBIGUOUS)
  judge/repairer DEEP nvidia/nemotron-3-ultra-550b-a55b
  posición «artículo 14» en borrador=391, en final=0
  modelos en eventos_traza: lightning-30b-a3b y ultra-550b-a55b

LIVE audit texto con artículo 9999 CT:
  dike CON_PROBLEMAS → repairer mechanical → TODAS_VERIFICADAS → publicar
  draft_has_9999=True  final_has_9999=False
  modelo juez nvidia/nemotron-3-ultra-550b-a55b

Plan B:
  Lightning empty_response (HTTP 502) si max_tokens<2048 o el system prompt es largo.
  Timeout LLM 90s (DESIGN 60s) para esos 2048 tokens.
  Markovian no conectado (Fase 4). H-MEM stub recall vacío (Fase 3).
```

---

## 2026-10-27 — Composer — Fase 3: sidecar H-MEM + memoria entre sesiones

| Campo | Valor |
|---|---|
| Fecha | 2026-10-27T05:01:16-03:00 |
| Modelo | Composer |
| Fase | Fase 3 H-MEM |
| Tarea | Sidecar `engines/` desde referencia Meterless H-MEM, HTTP DESIGN, cliente real, recall/remember en el loop, espejo `shield.refutadas`, tests A/B |
| Archivos | `engines/` (hmem referencia + `src/{hmem,server,main}.ts`), `shield/{engines,db,loop}.py`, `tests/{test_memory,test_loop,fakes}.py`, `scripts/fase3_memory.py` |
| Resultado | PASS. Conformidad H-MEM 13/13. Sidecar `:8790` hmem true, markovian false (honesto; Markovian es Fase 4). Shield `/healthz` engines true. Demo A refuta / B recuerda. pytest 14 passed. `~/.lexo` mtime 2026-09-22 intacto |

Desvío DESIGN § sidecar `/healthz` pedía `markovian:true`. Plan B HANDOFF: basta un engine; H-MEM es el obligatorio. Se anota y se deja `markovian:false`.

Traducción interna (la API DESIGN no cambia): `namespace` refutadas/trampas va en tags `ns:*` porque H-MEM asigna `namespace` como `domain/bucket`. `source` obligatorio = `dike-shield:<ns>`. Persistencia sidecar: `.local/hmem` (gitignored).

Arranque sidecar (sin sudo):

```text
cd engines && npm ci && npm start
# engines sidecar http://127.0.0.1:8790 hmem=true markovian=false
# primera vez también: cd engines/hmem/reference && npm ci
```

```text
$ cd engines/hmem/reference && npm test
 ✓ test/smoke.test.ts (10 tests)

$ HMEM_IMPL=$PWD/engines/hmem/reference/src/index.ts npx tsx engines/hmem/conformance/runner.ts
H-MEM conformance: implementation = .../engines/hmem/reference/src/index.ts
  record-validation
    PASS rv-001 a record with no source is rejected by construction
    PASS rv-002 a record with a source is accepted
  feedback-deltas
    PASS fd-001 helpful adds exactly +0.05 confidence and +1 accessCount
    PASS fd-002 not_helpful subtracts exactly 0.03
    PASS fd-003 wrong subtracts exactly 0.20 and adds the review tag
    PASS fd-004 confidence clamps at 0 (wrong at 0.1)
    PASS fd-005 confidence clamps at 1 (helpful at 0.98)
  ranking-order
    PASS ro-001 superseded penalty dominates: a superseded record ranks below a fresh one with identical content relevance
    PASS ro-002 confidence multiplies the whole score: identical records rank by confidence
  sleep-guardrails
    PASS sg-001 old low-access plain record archives; dream-derived record with identical age does not
  conflict-gate
    PASS cg-001 auto-resolve marks the loser supersededBy and deletes nothing
  ledger-audit
    PASS la-001 create then feedback reconstructs: actions in order, previous and new confidence present
  dream-boundary
    PASS db-001 dream proposals never materialize before approval; approval creates a long_term record with lineage
  13/13 checks passed

$ HMEM_IMPL=$PWD/engines/src/hmem.ts npx tsx engines/hmem/conformance/runner.ts
  13/13 checks passed

$ (cd engines && npm test)
✔ healthz is honest and remember/recall round-trip a refuted cite
ℹ pass 1

$ curl -sS http://127.0.0.1:8790/healthz
{"ok":true,"hmem":true,"markovian":false}

$ GET /healthz Shield (TestClient)
200 {'ok': False, 'zetaris': True, 'meterless': False, 'dike': True, 'engines': True, 'sample_mode': False}
# engines true (hmem). meterless false en este check: Nightshift /models no respondió; no es puerta de Fase 3.

$ uv run pytest -q
..............  [100%]
# 8 previos + fail-closed, http remember/recall, A/B, drafter evita, MemoryStore upsert, Postgres upsert

$ uv run python scripts/fase3_memory.py
sidecar_healthz {"ok": true, "hmem": true, "markovian": false}
store postgres
session_a 2fa6c41e-096e-492f-bd88-97d7b5d5bde4 decision publicar 9999_in_final False
session_b 2025af9c-9613-4f2e-a08c-b1d69d5fc2c6 decision publicar 9999_in_final False
traza_b
  paso=1 agente=router accion=responder salida=escenario=despido cubierto por el corpus
  paso=2 agente=memory accion=recordado de la sesión 2fa6c41e-096e-492f-bd88-97d7b5d5bde4 salida=recordado de la sesión 2fa6c41e-096e-492f-bd88-97d7b5d5bde4: artículo 9999 del Código del Trabajo
  paso=3 agente=drafter accion=borrador salida=Según el artículo 9999 del Código del Trabajo el plazo es de cinco días. El artículo 168 del Código del Trabajo permite reclamar el despido.
  ...
  paso=7 agente=repairer accion=reescritura salida=El artículo 168 del Código del Trabajo permite reclamar el despido ante el juzgado de letras del trabajo.
  paso=10 agente=judge accion=publicar salida=todas verificadas
PASS recordado de la sesión 2fa6c41e-096e-492f-bd88-97d7b5d5bde4
refutadas_9999_veces 4

stat ~/.lexo → 2026-09-22 05:23:13 -0300 (sin cambio)
No se pasó a Fase 4.
```

---

## 2026-10-27 — Composer — Fase 4: Markovian, banco y UI

| Campo | Valor |
|---|---|
| Fecha | 2026-10-27T14:00:28-03:00 |
| Modelo | Composer |
| Fase | Fase 4 Markovian + banco + UI |
| Tarea | Referencia Markovian, HTTP start/step, loop fail-closed, 30+20 samples, 4 corridas, UI con etiquetas, commitments ZIP |
| Archivos | `engines/markovian/`, `engines/src/{markovian,markovianHttp,server,main}.ts`, `shield/{engines,loop,db,api}.py`, `shield/bench/`, `shield/web/`, `data/samples/*`, `tests/{test_bench,test_ui,test_memory}.py`, `scripts/{verify_trampas,fase4_bench}.py` |
| Resultado | PASS. Markovian conformidad 8/8. Sidecar hmem+markovian true. Banco 4 corridas (fakes): sin escudo tasa 0.5, con escudo 0.0. Trampas 20/20 FALLO. pytest 19 passed. Nightshift /models no ok: banco vivo omitido (plan B). `~/.lexo` intacto. No Fase 5. |

Arranque sidecar:

```text
cd engines && npm ci && npm start
# engines sidecar http://127.0.0.1:8790 hmem=true markovian=true
cd engines/markovian/reference && npm ci   # primera vez
```

```text
$ MARKOVIAN_IMPL=.../engines/markovian/reference/src/index.ts npx tsx engines/markovian/conformance/runner.ts
  PASS eff-001 ... snap-001 snap-002 ovl-001 lab-001 ref-001 mrk-001 cfg-001
  8/8 checks passed
$ MARKOVIAN_IMPL=.../engines/src/markovian.ts npx tsx engines/markovian/conformance/runner.ts
  8/8 checks passed

$ curl -sS http://127.0.0.1:8790/healthz
{"ok":true,"hmem":true,"markovian":true}

$ POST /markovian/start + /markovian/step decision=publicar → done=true step=1

$ GET Shield /healthz
200 {ok:false, zetaris:true, meterless:false, dike:true, engines:true, sample_mode:false}

$ uv run python scripts/verify_trampas.py
20/20 trampas sin colisión
# 20 FALLO (inexistente/ambigua/derogada/cuerpo_equivocado)

$ banco 4 corridas (LLM fake, n=2):
FAST escudo=False n=2 total=4 bad=2 tasa=0.5
FAST escudo=True  n=2 total=4 bad=0 tasa=0.0
DEEP escudo=False n=2 total=4 bad=2 tasa=0.5
DEEP escudo=True  n=2 total=4 bad=0 tasa=0.0

$ uv run python scripts/fase4_bench.py
nightshift_models False
SKIP live bench: Nightshift /models not ok; pytest covers 4 runs with fakes

$ (cd engines && npm test) → pass 1
$ uv run pytest -q
...................  [100%]
# 19: adapter, loop, memory, bench 4 corridas, UI etiquetas, samples

stat ~/.lexo → 2026-09-22 05:23:13 -0300 (sin cambio)
UI: GET / sirve shield/web; etiquetas DESIGN §6 en index.html/app.js.
No se pasó a Fase 5 (SAMPLE_MODE grabado, README, deck, video).
```

---

## 2026-10-27 — Composer — Fase 5: SAMPLE_MODE, README, instalación, deck y video

| Campo | Valor |
|---|---|
| Fecha | 2026-10-27T14:30:15-03:00 |
| Modelo | Composer |
| Fase | Fase 5 endurecer y documentar |
| Tarea | SAMPLE_MODE + data/cache, README EN, SPONSORS.md, sha256, escaneo de secretos, instalación limpia cronometrada, deck EN, video 1–4 min |
| Archivos | `shield/{llm,api}.py`, `shield/web/app.js`, `data/cache/**`, `tests/test_sample_mode.py`, `README.md`, `docs/SPONSORS.md`, `.env.example`, `docs/deck/*`, `docs/video/*`, `scripts/record_sample.py`, `docs/CURSOR_LOG.md` |
| Resultado | PASS tests 24 (copia limpia 23 + 1 skip por SHIELD_DB_URL placeholder). SAMPLE_MODE sirve Lightning 30B / Ultra 550B de la corrida 2026-10-27 sin Runtime. sha256 0 FAILED. rg sin tokens vivos. Instalación limpia 42 s. Deck 10 slides. Video 110 s. Nightshift TCP :8088 timeout: video usa recibo de Fase 2, no captura de Console. `~/.lexo` intacto. Agente no hace push (Fase 6 es del autor). |

Nightshift:

```text
python3 TCP 192.168.122.50:8088 → TimeoutError
# SAMPLE_MODE reconstruye la corrida viva Fase 2 (CURSOR_LOG 2026-10-27T04:36)
# FAST nvidia/nemotron-3.5-lightning-30b-a3b 26922ms; artículo 14 pos=391
# DEEP nvidia/nemotron-3-ultra-550b-a55b; audit 9999 in / 9999 out
```

```text
$ uv run pytest -q
........................  [100%]
# 24: 19 previos + SAMPLE_MODE (drafter art.14 pos 391, judge reparar/publicar, repairer sin 9999/14, SAMPLE_MODE=false no lee caché)

$ (cd engines && npm test)
✔ healthz is honest and remember/recall round-trip a refuted cite
ℹ pass 1

$ (cd vendor/dike && sha256sum -c --quiet ../../PREEXISTING.sha256)
# exit 0

$ rg -l -i '(api[_-]?key|token|secret)\s*[:=]\s*\S{12,}'  (excl. .env node_modules .venv)
# solo código y placeholders; sin nvapi-/sk-/Bearer vivo
# .env.example: <token-de-la-console-de-nightshift> etc.

Instalación limpia /tmp/dike-shield-fase5 (sin .venv, node_modules, .env, .local):
  cp .env.example .env && chmod 600 .env
  uv sync
  (cd engines && npm ci) && (cd engines/hmem/reference && npm ci) && (cd engines/markovian/reference && npm ci)
  uv run python scripts/setup_dike.py
  uv run pytest -q
START 2026-10-27T14:29:33-03:00
END   2026-10-27T14:30:15-03:00
elapsed_sec=42
PASS corpus=.../tmp/dike-shield-fase5/.local/dike-home/users/shield/starter/chile-base
PASS key=.../demo-content-signing-key.pem created mode=0o600
PASS ~/.lexo unchanged
...............s........  # SKIP tests/test_memory.py: SHIELD_DB_URL missing (placeholder del example)

Deck: docs/deck/dike-shield.pptx (validate.py PASSED, 10 slides EN)
Video: docs/video/dike-shield.mp4 duration=110s 1920x1080
  beats: pregunta → art.14/9999 → repair → commitment → H-MEM → banco 50%/0% → recibo Nightshift token *** → hueco VM
  no hay screenshot de Console (VM caída). Re-filmar cuando suba. SAMPLE_MODE banner: 2026-10-27

stat ~/.lexo → 2026-09-22 05:23:13 -0300 (sin cambio)
No push. Fase 6: el autor crea remoto, publica y completa HackOS.
```

---

## 2026-10-27 — Composer — win11 up, Console live, video actualizado

| Campo | Valor |
|---|---|
| Fecha | 2026-10-27T17:29:45-03:00 |
| Modelo | Composer |
| Fase | Video / Runtime vivo |
| Tarea | Arrancar `win11`, Nightshift Console, recortar token, regrabar `docs/video/dike-shield.mp4` |
| Archivos | `docs/video/{build_frames.py,README.md,console-live.png,dike-shield.mp4,frames/09.png,frames/10.png}`, `docs/CURSOR_LOG.md` |
| Resultado | PASS Console + `/models`. VM running, Hotspot `192.168.122.50`, `GET /v1/models` 200 (86 ids, Lightning 30B + Ultra 550B). Video 110 s con framebuffer real. `chat/completions` nuevo: HTTP 502 NVIDIA. `~/.lexo` intacto. No push. |

```text
$ .hackathon/setup/03_ram.sh stop   # Langfuse/etc. 10 GB libres
$ virsh -c qemu:///system start win11
Domain 'win11' started
State: running  2 vCPU  8 GiB
SPICE 127.0.0.1:5900
ARP 52:54:00:92:1e:2c → 192.168.122.50

# Nightshift v1.2.7: meterlessd down at boot; Ctrl+K → "Start the local runtime"
$ python3 TCP 192.168.122.50:8088 → CONNECT
$ GET $METERLESS_BASE_URL/models → 200 n=86
  nvidia/nemotron-3.5-lightning-30b-a3b
  nvidia/nemotron-3-ultra-550b-a55b
Console: online · Hotspot ON THE NETWORK · 192.168.122.50
$ POST /chat/completions model=lightning-30b → HTTP 502 (kind=nvidia) 17:27 CL

Video:
  python3 docs/video/build_frames.py
  ffmpeg … docs/video/dike-shield.mp4
  duration=110s 1920x1080
  card 09 = virsh framebuffer Console, API key → Bearer ***
  card 10 = GET /models 200 + 502 NVIDIA (no fake chat receipt)

stat ~/.lexo → 2026-09-22 05:23:13 -0300 (sin cambio)
Langfuse detenido para RAM; Zetaris healthy; shield-db healthy; engines :8790 hmem+markovian.
No push.
```




