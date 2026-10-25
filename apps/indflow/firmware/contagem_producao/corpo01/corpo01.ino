// Caminho completo: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\firmware\contagem_producao\corpo01\corpo01.ino
// Data/hora do ultimo recode: 2026-10-25 06:06:09 (America/Bahia)
// Motivo: Organizar os firmwares no projeto GestFlow/IndFlow; somente cabecalho atualizado, funcionamento preservado.
// OBS: Ajuste SEND_TO_DEV e SEND_TO_PROD conforme necessidade. PROD pode exigir API_KEY_PROD.

// =====================================================
// FIX COMPILACAO (ARDUINO AUTO-PROTOTYPE)
// =====================================================
// O Arduino gera prototypes automaticamente e pode colocar:
//   void enviarUtilidade(Utilidade &u);
// antes da definicao do struct Utilidade.
// Forward-declaration aqui garante que o tipo exista no momento do prototype.
struct Utilidade;

#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include <time.h>
#include <sys/time.h>

Preferences prefs;

// =====================================================
// DEBUG — VALIDAR SE O ESP ESTA MANDANDO ts_ms
// =====================================================
static const bool DEBUG_PRINT_PAYLOAD = true;     // imprime JSON completo no Serial antes do POST
static const bool DEBUG_PRINT_HTTP_CODE = true;   // imprime HTTP status code
static const bool DEBUG_PRINT_TS_ONLY = false;    // se true, imprime só ts_ms e ts_iso_local (não imprime JSON completo)

void debugPrintTimestampFields(const JsonDocument &doc) {
  if (!DEBUG_PRINT_PAYLOAD && !DEBUG_PRINT_TS_ONLY) return;

  uint64_t ts_ms = 0ULL;
  const char* ts_iso = "";

  if (doc.containsKey("ts_ms")) {
    ts_ms = (uint64_t)doc["ts_ms"];
  }
  if (doc.containsKey("ts_iso_local")) {
    ts_iso = doc["ts_iso_local"] | "";
  }

  Serial.printf("DBG ts_ms=%llu ts_iso_local=%s\n", (unsigned long long)ts_ms, ts_iso);
}

void debugPrintPayload(const char* label, const String &payload) {
  if (!DEBUG_PRINT_PAYLOAD) return;
  Serial.printf("DBG POST %s JSON:\n", label);
  Serial.println(payload);
}

// =====================================================
// TEMPO (NTP) — TIMESTAMP VEM DO ESP
// =====================================================
// Bahia (UTC-3). Sem horario de verao.
static const long GMT_OFFSET_SEC = -3L * 3600L;
static const int DAYLIGHT_OFFSET_SEC = 0;
static const char* NTP_SERVER_1 = "pool.ntp.org";
static const char* NTP_SERVER_2 = "time.google.com";

static bool g_time_ok = false;
static unsigned long g_last_ntp_sync_ms = 0;
static const unsigned long NTP_RESYNC_INTERVAL_MS = 6UL * 60UL * 60UL * 1000UL; // 6h

void syncTimeNtpIfNeeded();
uint64_t nowEpochMs();
String nowIsoLocal();
void attachTimestamp(JsonDocument &doc);

// =====================================================
// WIFI - LISTA DE REDES (PROTOTIPO)
// =====================================================
struct WifiCred {
  const char* ssid;
  const char* pass;
};

WifiCred redes[] = {
  {"Netto Santana", "12345678"},
  {"jpclim", "jpclim2020"},
  {"IMP-TA", "5858106058"},
  {"INTELBRAS", "life2025"},
  {"MELO 2.4G", "240117071205"},
  {"wifizone_ nettos_988708374", "Matheus123"},
};

const int TOTAL_REDES = sizeof(redes) / sizeof(redes[0]);
int wifiIndexAtual = 0;

unsigned long wifiStartAttempt = 0;
const unsigned long WIFI_TIMEOUT_MS = 8000;

// =====================================================
// ENDPOINTS (PROD + DEV)
// =====================================================
String endpointProdProducao   = "https://web-production-a1350.up.railway.app/machine/update";
String endpointProdUtilidades = "https://web-production-a1350.up.railway.app/utilidades/update";

String endpointDevProducao    = "https://dev-indflow-production.up.railway.app/machine/update";
String endpointDevUtilidades  = "https://dev-indflow-production.up.railway.app/utilidades/update";


// =====================================================
// SELECAO DE AMBIENTE (ENVIO)
// - Para teste temporario, voce pode enviar para DEV e PROD ao mesmo tempo.
// - CUIDADO: isso dobra trafego e pode aumentar atraso se a rede estiver ruim.
// =====================================================
static const bool SEND_TO_DEV  = true;
static const bool SEND_TO_PROD = true;
// =====================================================
// API KEYS
// - DEV: necessario para /machine/update (como voce ja usa hoje)
// - PROD: deixe vazio se o PROD nao exigir chave. Se exigir, preencha.
// =====================================================
const char* API_KEY_DEV  = "IND_1d970b88de9acd2f172493e60e76d914";
const char* API_KEY_PROD = "IND_35fd0ff8431b3968cfd81100930ef6eb";

// =====================================================
// PINOS PRODUCAO
// =====================================================
const int PIN_STATUS = 15;   // AUTO/MANUAL (modo)
const int PIN_PULSO  = 18;   // pulso de producao

// =====================================================
// PINOS UTILIDADES
// =====================================================
const int GERADOR_LIGADO = 4;
const int GERADOR_FALHA  = 5;
const int COMP_LIGADO    = 19;
const int COMP_FALHA     = 21;

// =====================================================
// VARIAVEIS PRODUCAO
// =====================================================
String machine_id   = "corpo01";
String machine_name = "CORPO01";

volatile unsigned long producao_turno = 0;

// Modo (AUTO/MANUAL) vem do PIN_STATUS
bool status_auto = false;

// RUN (PRODUZINDO/PARADO) vem do comportamento do pulso
bool run_produzindo = false;
bool last_run_produzindo = false;

// =====================================================
// PULSO / DEBOUNCE
// =====================================================
volatile bool pulso_irq = false;

bool sensor_presente = false;
unsigned long lastStateChangeMs = 0;
const unsigned long STABLE_MS = 30;

// Ultimo momento em que houve qualquer mudanca no PIN_PULSO (para detectar atividade)
unsigned long lastPulseMs = 0;

// =====================================================
// TEMPO ENTRE CICLOS (DEBUG)
// =====================================================
unsigned long lastCycleTime = 0;
unsigned long totalCycleTime = 0;
unsigned long cycleSamples  = 0;

// =====================================================
// REGRAS DE ENVIO (PRODUCAO)
// =====================================================
unsigned long lastSendMs = 0;
const unsigned long SEND_INTERVAL_MS = 30000; // 30 segundos

// =====================================================
// HOUR TICK (PING) - GARANTE UPDATE NA VIRADA DA HORA
// - Se a maquina ficar PARADA, nao envia nada hoje, e o backend pode manter saldo da hora anterior
// - Este ping dispara 1 vez por hora (baseado no horario NTP do ESP)
// - Se nao houver WiFi na virada, marca como pendente e envia assim que reconectar
// =====================================================
static uint32_t g_hour_epoch_seen = 0;
static uint32_t g_hour_epoch_last_sent = 0;
static uint32_t g_hour_epoch_pending = 0;
static const unsigned long HOUR_TICK_MIN_SEND_GAP_MS = 1500; // evita duplicar envios no mesmo segundo

const unsigned long STOP_TRIGGER_MS  = 3000;  // 3 segundos

// =====================================================
// UTILIDADES
// =====================================================
struct Utilidade {
  const char* id;
  int ligado;
  int falha;
  int last_ligado;
  int last_falha;
  bool pendente;
};

Utilidade gerador    = {"util_ger01", 0, 0, -1, -1, false};
Utilidade compressor = {"util_comp01", 0, 0, -1, -1, false};

// =====================================================
// ISR
// =====================================================
void IRAM_ATTR isrMudou() {
  pulso_irq = true;
}

// =====================================================
// TEMPO (NTP) — FUNCOES
// =====================================================
void syncTimeNtpNow(){
  if (WiFi.status() != WL_CONNECTED) return;

  configTime(GMT_OFFSET_SEC, DAYLIGHT_OFFSET_SEC, NTP_SERVER_1, NTP_SERVER_2);

  const unsigned long t0 = millis();
  time_t nowSec = 0;

  while ((millis() - t0) < 8000UL){
    time(&nowSec);
    if (nowSec > 1700000000) break;
    delay(250);
  }

  time(&nowSec);
  if (nowSec > 1700000000){
    g_time_ok = true;
    g_last_ntp_sync_ms = millis();
  }
}

void syncTimeNtpIfNeeded(){
  if (WiFi.status() != WL_CONNECTED) return;

  if (!g_time_ok){
    syncTimeNtpNow();
    return;
  }

  if ((millis() - g_last_ntp_sync_ms) >= NTP_RESYNC_INTERVAL_MS){
    syncTimeNtpNow();
  }
}

uint64_t nowEpochMs(){
  syncTimeNtpIfNeeded();

  struct timeval tv;
  gettimeofday(&tv, nullptr);

  if (tv.tv_sec <= 0) return 0ULL;
  if (tv.tv_sec < 1700000000) return 0ULL;

  return (uint64_t)tv.tv_sec * 1000ULL + (uint64_t)(tv.tv_usec / 1000ULL);
}

String nowIsoLocal(){
  time_t nowSec;
  time(&nowSec);
  if (nowSec < 1700000000) return String("");

  struct tm tmLocal;
  localtime_r(&nowSec, &tmLocal);

  char buf[32];
  strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%S", &tmLocal);
  return String(buf);
}

void attachTimestamp(JsonDocument &doc){
  const uint64_t ts = nowEpochMs();

  if (ts > 0ULL){
    doc["ts_ms"] = ts;
    doc["ts_iso_local"] = nowIsoLocal();
  }else{
    doc["ts_ms"] = 0;
    doc["ts_iso_local"] = "";
  }

  doc["ts_esp_ms"] = (uint32_t)millis();
}

// =====================================================
// WIFI - CONEXAO MULTI-REDE
// =====================================================
void connectWiFi() {

  if (WiFi.status() == WL_CONNECTED) {
    syncTimeNtpIfNeeded();
    return;
  }

  if (wifiStartAttempt == 0) {
    WiFi.begin(redes[wifiIndexAtual].ssid, redes[wifiIndexAtual].pass);
    wifiStartAttempt = millis();
    return;
  }

  if (millis() - wifiStartAttempt > WIFI_TIMEOUT_MS) {
    WiFi.disconnect();
    wifiIndexAtual = (wifiIndexAtual + 1) % TOTAL_REDES;
    wifiStartAttempt = 0;
  }
}

// =====================================================
// FLASH
// =====================================================
void salvarFlash(unsigned long valor) {
  prefs.putULong("producao", valor);
}

// =====================================================
// HTTP HELPERS
// =====================================================
bool postJsonWithKeyEx(const String& url, const String& payload, const char* apiKey, String* responseOut, int* codeOut) {
  if (WiFi.status() != WL_CONNECTED) return false;

  HTTPClient http;

  // HTTPS no ESP32 precisa de WiFiClientSecure configurado.
  // Railway usa TLS com cadeia que pode falhar sem CA. Para DEV, usamos setInsecure()
  // para garantir conectividade e validar o fluxo (ts_ms + resposta 200).
  // Se quiser endurecer depois, trocamos por root CA.
  WiFiClientSecure secureClient;
  secureClient.setInsecure();

  http.setTimeout(6000);

  if (url.startsWith("https://")) {
    http.begin(secureClient, url);
  } else {
    http.begin(url);
  }

  http.addHeader("Content-Type", "application/json");

  if (apiKey != nullptr && strlen(apiKey) > 0) {
    http.addHeader("X-API-Key", apiKey);
  }

  int code = http.POST(payload);

  if (DEBUG_PRINT_HTTP_CODE) {
    Serial.printf("DBG HTTP POST code=%d url=%s\n", code, url.c_str());
  }

  if (codeOut) {
    *codeOut = code;
  }

  if (responseOut) {
    *responseOut = http.getString();
  }

  http.end();

  return (code >= 200 && code < 300);
}

bool postJsonWithKey(const String& url, const String& payload, const char* apiKey) {
  return postJsonWithKeyEx(url, payload, apiKey, nullptr, nullptr);
}

bool postJson(const String& url, const String& payload) {
  return postJsonWithKey(url, payload, nullptr);
}
// =====================================================
// ENVIO - PRODUCAO (DEV/PROD)
// - Pode enviar para DEV e PROD ao mesmo tempo (SEND_TO_DEV / SEND_TO_PROD)
// - Para evitar reset duplo, comandos (reset_counter) sao processados somente da resposta DEV
// =====================================================
bool enviarProducao(unsigned long valor) {
  return enviarProducao(valor, "run");
}

static bool _postProducao(const String& url, const String& payload, const char* apiKey, String* respOut, int* codeOut) {
  if (apiKey && apiKey[0]) {
    return postJsonWithKeyEx(url, payload, apiKey, respOut, codeOut);
  }
  return postJsonWithKeyEx(url, payload, nullptr, respOut, codeOut);
}

bool enviarProducao(unsigned long valor, const char* motivo) {
  if (WiFi.status() != WL_CONNECTED) return false;

  StaticJsonDocument<512> json;
  attachTimestamp(json);

  json["mac"]            = WiFi.macAddress();
  json["machine_id"]     = machine_id;
  json["nome"]           = machine_name;
  json["status"]         = status_auto ? "AUTO" : "MANUAL";
  json["run"]            = run_produzindo ? 1 : 0;
  json["producao_turno"] = valor;
  json["tempo_medio_ms"] = (cycleSamples > 0) ? (totalCycleTime / cycleSamples) : 0;
  json["event"]          = (motivo && motivo[0]) ? motivo : "run";

  if (DEBUG_PRINT_TS_ONLY || DEBUG_PRINT_PAYLOAD) {
    debugPrintTimestampFields(json);
  }

  String payload;
  serializeJson(json, payload);

  if (DEBUG_PRINT_PAYLOAD) {
    debugPrintPayload("producao", payload);
  }

  bool okAny = false;

  // DEV
  String respDev;
  int codeDev = 0;
  bool okDev = false;

  if (SEND_TO_DEV) {
    okDev = _postProducao(endpointDevProducao, payload, API_KEY_DEV, &respDev, &codeDev);
    if (okDev) {
      okAny = true;
      Serial.println("Producao enviada [DEV]");
    } else {
      Serial.println("ERRO: Producao falhou em DEV");
    }
  }

  // PROD
  String respProd;
  int codeProd = 0;
  bool okProd = false;

  if (SEND_TO_PROD) {
    okProd = _postProducao(endpointProdProducao, payload, API_KEY_PROD, &respProd, &codeProd);
    if (okProd) {
      okAny = true;
      Serial.println("Producao enviada [PROD]");
    } else {
      Serial.println("ERRO: Producao falhou em PROD");
    }
  }

  if (okAny) {
    lastSendMs = millis();
  }

  // Comandos: processar somente a resposta DEV (evita reset duplo)
  if (okDev && respDev.length() > 0) {
    StaticJsonDocument<384> rjson;
    DeserializationError err = deserializeJson(rjson, respDev);

    if (!err) {
      const char* cmd = rjson["cmd"] | "";

      if (strcmp(cmd, "reset_counter") == 0) {
        String cmdId = "";

        if (rjson.containsKey("cmd_id")) {
          cmdId = rjson["cmd_id"].as<String>();
        }

        Serial.printf("CMD recebido (DEV): reset_counter | cmd_id=%s\n", cmdId.c_str());

        // Zera o contador local e persiste
        producao_turno = 0;
        salvarFlash(producao_turno);

        // Zera medicao de ciclo (opcional, evita medias artificiais apos reset)
        totalCycleTime = 0;
        cycleSamples = 0;
        lastCycleTime = 0;

        // Envia ACK imediato (para o servidor confirmar que o reset foi aplicado)
        StaticJsonDocument<512> ack;
        attachTimestamp(ack);

        ack["mac"]            = WiFi.macAddress();
        ack["machine_id"]     = machine_id;
        ack["nome"]           = machine_name;
        ack["status"]         = status_auto ? "AUTO" : "MANUAL";
        ack["run"]            = run_produzindo ? 1 : 0;
        ack["producao_turno"] = producao_turno;
        ack["reset_ack"]      = 1;

        if (cmdId.length() > 0) {
          ack["cmd_id"] = cmdId;
        }

        String ackPayload;
        serializeJson(ack, ackPayload);

        if (DEBUG_PRINT_PAYLOAD) {
          debugPrintPayload("reset_ack", ackPayload);
        }

        bool okAck = postJsonWithKey(endpointDevProducao, ackPayload, API_KEY_DEV);

        if (okAck) {
          Serial.println("ACK reset_counter enviado [DEV]");
        } else {
          Serial.println("ERRO: ACK reset_counter falhou em DEV");
        }
      }
    } else {
      Serial.printf("DBG resposta DEV nao-JSON (len=%u)\n", (unsigned int)respDev.length());
    }
  }

  return okAny;
}

// =====================================================
// ENVIO - UTILIDADES (DEV/PROD)
// =====================================================
static bool _postUtilidades(const String& url, const String& payload) {
  return postJson(url, payload);
}

void enviarUtilidade(Utilidade &u) {
  if (!u.pendente) return;
  if (WiFi.status() != WL_CONNECTED) return;

  StaticJsonDocument<256> json;
  attachTimestamp(json);

  json["machine_id"] = u.id;
  json["ligado"]     = u.ligado;
  json["falha"]      = u.falha;

  if (DEBUG_PRINT_TS_ONLY || DEBUG_PRINT_PAYLOAD) {
    debugPrintTimestampFields(json);
  }

  String payload;
  serializeJson(json, payload);

  if (DEBUG_PRINT_PAYLOAD) {
    debugPrintPayload("utilidades", payload);
  }

  bool okAny = false;

  if (SEND_TO_DEV) {
    bool okDev = _postUtilidades(endpointDevUtilidades, payload);
    if (okDev) {
      okAny = true;
      Serial.printf("Utilidade enviada [DEV]: %s | ligado=%d falha=%d\n", u.id, u.ligado, u.falha);
    } else {
      Serial.printf("ERRO: Utilidade falhou em DEV: %s\n", u.id);
    }
  }

  if (SEND_TO_PROD) {
    bool okProd = _postUtilidades(endpointProdUtilidades, payload);
    if (okProd) {
      okAny = true;
      Serial.printf("Utilidade enviada [PROD]: %s | ligado=%d falha=%d\n", u.id, u.ligado, u.falha);
    } else {
      Serial.printf("ERRO: Utilidade falhou em PROD: %s\n", u.id);
    }
  }

  if (okAny) {
    u.last_ligado = u.ligado;
    u.last_falha  = u.falha;
    u.pendente    = false;
  }
}

// =====================================================
// TASK CONTAGEM - CORE 1
// =====================================================
void taskContagem(void* pv) {
  for (;;) {
    status_auto = (digitalRead(PIN_STATUS) == LOW);

    if (pulso_irq) {
      pulso_irq = false;
      lastStateChangeMs = millis();
      lastPulseMs = lastStateChangeMs;
    }

    if (millis() - lastStateChangeMs >= STABLE_MS) {
      bool leitura_atual = (digitalRead(PIN_PULSO) == LOW);

      if (leitura_atual != sensor_presente) {
        bool antes = sensor_presente;
        sensor_presente = leitura_atual;

        if (antes && !sensor_presente && status_auto) {
          producao_turno++;
          salvarFlash(producao_turno);

          unsigned long agora = millis();

          if (lastCycleTime > 0) {
            unsigned long delta = agora - lastCycleTime;
            totalCycleTime += delta;
            cycleSamples++;
            Serial.printf("Peca: %lu | dt: %lu ms | Media: %lu ms\n",
                          producao_turno, delta, totalCycleTime / cycleSamples);
          } else {
            Serial.printf("Peca: %lu | primeira contagem\n", producao_turno);
          }

          lastCycleTime = agora;
        }
      }
    }

    int gL = (digitalRead(GERADOR_LIGADO) == LOW);
    int gF = (digitalRead(GERADOR_FALHA)  == LOW);

    if (gL != gerador.last_ligado || gF != gerador.last_falha) {
      gerador.ligado = gL;
      gerador.falha  = gF;
      gerador.pendente = true;
    }

    int cL = (digitalRead(COMP_LIGADO) == LOW);
    int cF = (digitalRead(COMP_FALHA)  == LOW);

    if (cL != compressor.last_ligado || cF != compressor.last_falha) {
      compressor.ligado = cL;
      compressor.falha  = cF;
      compressor.pendente = true;
    }

    vTaskDelay(1);
  }
}

// =====================================================
// TASK ENVIO - CORE 0
// =====================================================
void taskEnvio(void* pv) {
  for (;;) {
    connectWiFi();
    syncTimeNtpIfNeeded();

    enviarUtilidade(gerador);
    enviarUtilidade(compressor);

    bool run_now = (millis() - lastPulseMs <= STOP_TRIGGER_MS);
    run_produzindo = run_now;

    // -------------------------------------------------
    // HOUR TICK: detecta virada de hora (via time() local)
    // Mesmo se a maquina estiver parada, marca pendente para enviar.
    // -------------------------------------------------
    time_t nowSec = 0;
    time(&nowSec);
    if (nowSec > 1700000000) {
      uint32_t hourEpoch = (uint32_t)(nowSec / 3600);
      if (g_hour_epoch_seen == 0 || hourEpoch != g_hour_epoch_seen) {
        g_hour_epoch_seen = hourEpoch;
        g_hour_epoch_pending = hourEpoch;
      }
    }

    // Envia ping da virada assim que houver WiFi (e evita duplicar envios colados)
    if (WiFi.status() == WL_CONNECTED && g_hour_epoch_pending != 0 && g_hour_epoch_pending != g_hour_epoch_last_sent) {
      if (millis() - lastSendMs >= HOUR_TICK_MIN_SEND_GAP_MS) {
        bool okTick = enviarProducao(producao_turno, "hour_tick");
        if (okTick) {
          g_hour_epoch_last_sent = g_hour_epoch_pending;
          g_hour_epoch_pending = 0;
        }
      }
    }

    if (run_produzindo != last_run_produzindo) {
      last_run_produzindo = run_produzindo;
      enviarProducao(producao_turno);
    }

    if (run_produzindo && (millis() - lastSendMs >= SEND_INTERVAL_MS)) {
      enviarProducao(producao_turno);
    }

    vTaskDelay(100 / portTICK_PERIOD_MS);
  }
}

// =====================================================
// SETUP
// =====================================================
void setup() {
  Serial.begin(115200);

  pinMode(PIN_STATUS, INPUT_PULLUP);
  pinMode(PIN_PULSO,  INPUT_PULLUP);

  pinMode(GERADOR_LIGADO, INPUT_PULLUP);
  pinMode(GERADOR_FALHA,  INPUT_PULLUP);
  pinMode(COMP_LIGADO,    INPUT_PULLUP);
  pinMode(COMP_FALHA,     INPUT_PULLUP);

  attachInterrupt(digitalPinToInterrupt(PIN_PULSO), isrMudou, CHANGE);

  prefs.begin("indflow", false);
  producao_turno = prefs.getULong("producao", 0);

  WiFi.mode(WIFI_STA);

  sensor_presente = (digitalRead(PIN_PULSO) == LOW);
  lastStateChangeMs = millis();
  lastPulseMs = millis();

  run_produzindo = false;
  last_run_produzindo = false;

  xTaskCreatePinnedToCore(taskContagem, "taskContagem", 8192, NULL, 2, NULL, 1);
  xTaskCreatePinnedToCore(taskEnvio,    "taskEnvio",    8192, NULL, 1, NULL, 0);

  Serial.println("IndFlow iniciado: producao (OR) e utilidades por mudanca [DEV ONLY]");
}

void loop() {
  vTaskDelay(portMAX_DELAY);
}

// =====================================================
// GIT (copiar e colar)
// =====================================================
// git add -A
// git commit -m "fw: fix compile (forward-declare Utilidade) mantendo log de payload/HTTP"
// git push
