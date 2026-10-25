// Caminho completo: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\firmware\controle_cracha\versao_anterior\versao_anterior.ino
// Data/hora do ultimo recode: 2026-10-25 06:06:09 (America/Bahia)
// Motivo: Organizar os firmwares no projeto GestFlow/IndFlow; somente cabecalho atualizado, funcionamento preservado.

#include <Arduino.h>
#include <Preferences.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <time.h>
#include <LittleFS.h>
#include <Wire.h>
#include <sys/time.h>
#include <esp_timer.h>
#if __has_include(<esp_sntp.h>)
  #include <esp_sntp.h>
#else
  #include <lwip/apps/sntp.h>
#endif

Preferences prefs;

// ===================== CONFIGURACAO DE PINOS =====================
// Entradas Wiegand
const int PIN_WIEGAND_D0 = 23;
const int PIN_WIEGAND_D1 = 22;

// Entrada de comando
const int PIN_BOTAO_LIGA_DESLIGA = 32;
const int PIN_EMERGENCIA_NF = 33;

// Saidas
const int PIN_RELE_AUTORIZACAO = 18;
const int PIN_RELE_COMANDO = 19;
const int PIN_LED_STATUS = 21;

// Relogio externo ZS-042 (DS3231), usando pinos I2C livres.
const int PIN_RTC_SDA = 25;
const int PIN_RTC_SCL = 26;
const uint8_t ENDERECO_RTC_DS3231 = 0x68;

// ===================== TESTE DE RUIDO =====================
// false = saida do LED de status fica inibida para evitar pulsos eletricos durante testes.
// true  = LED de status volta a funcionar normalmente.
const bool HABILITAR_LED_STATUS = false;

// ===================== CONFIGURACAO DOS RELES =====================
// Se o modulo de rele acionar com nivel baixo, mantenha true.
// Se o rele ficar invertido no teste, altere para false.
const bool RELE_ATIVO_EM_LOW = true;

// ===================== MODO TESTE =====================
// true = permite que o cartao mestre tambem libere a maquina.
// false = cartao mestre serve somente para administracao.
const bool PERMITIR_MESTRE_COMO_USUARIO_TESTE = false;

// ===================== CONFIGURACAO WIFI / GOOGLE SHEETS =====================
// Preencha o SSID e a senha do Wi-Fi 2.4 GHz antes de gravar no ESP32.
// Exemplo de SSID: hotspot do celular Redmi configurado em 2.4 GHz.
const char* WIFI_SSID = "Netto Santana";
const char* WIFI_SENHA = "12345678";

const char* URL_LOGS_GOOGLE_SHEETS = "https://script.google.com/macros/s/AKfycbzGFGUd4SOBzzFLidfpOq63jlWS8XfMnWff1Swcsbfa_JS8Cr230DM73DbYZfE8FLewyA/exec";
const char* DISPOSITIVO_ID = "ESP32_CRACHA_01";

bool wifiConectado = false;
TaskHandle_t tarefaLogsHandle = NULL;
SemaphoreHandle_t mutexFilaLogs = NULL;

// ===================== TEMPOS =====================
const unsigned long TEMPO_AUTORIZACAO_MS = 30000;
const unsigned long TEMPO_RESTART_MS = 30000;
const unsigned long TEMPO_MESTRE_SEGURADO_MS = 5000;
const unsigned long TEMPO_MODO_ADMIN_MS = 20000;
const unsigned long TEMPO_PULSO_RELE_MS = 500;
const unsigned long TEMPO_DEBOUNCE_BOTAO_MS = 80;
const unsigned long TEMPO_DEBOUNCE_EMERGENCIA_MS = 80;
const unsigned long TEMPO_WIEGAND_FINAL_US = 25000;
const unsigned long TEMPO_RELEITURA_CARTAO_MS = 1200;
const unsigned long TEMPO_BLOQUEIO_WIEGAND_APOS_RELE_MS = 2000;

// ===================== CARTAO MESTRE =====================
// Cracha mestre fixo. Serve somente para cadastrar/descadastrar usuarios.
const uint64_t CARTAO_MESTRE_FIXO = 0x0E6242DULL;
uint64_t cartaoMestre = CARTAO_MESTRE_FIXO;

// ===================== ESTADOS DO SISTEMA =====================
bool autorizado = false;
bool modoAdmin = false;
bool maquinaLigada = false;

unsigned long inicioAutorizacao = 0;
unsigned long inicioRestart = 0;
unsigned long inicioModoAdmin = 0;

bool aguardandoRestart = false;
bool estadoReleAutorizacao = false;
bool estadoReleComando = false;
bool estadoLedStatus = false;
bool monitorSerialAtivo = false;
unsigned long ultimoMonitorSerial = 0;
const unsigned long TEMPO_MONITOR_SERIAL_MS = 1000;

// ===================== COMANDOS SERIAIS =====================
bool aguardandoConfirmacaoReset = false;
unsigned long inicioConfirmacaoReset = 0;
const unsigned long TEMPO_CONFIRMACAO_RESET_MS = 15000;

// ===================== EMERGENCIA =====================
// Ligacao: GND -> contato NF da emergencia -> GPIO33.
// Normal: LOW. Emergencia acionada ou fio rompido: HIGH.
bool emergenciaAtiva = false;
bool ultimoEstadoEmergencia = LOW;
bool estadoEmergenciaEstavel = LOW;
unsigned long ultimoDebounceEmergencia = 0;

// ===================== BOTAO =====================
bool ultimoEstadoBotao = HIGH;
bool estadoBotaoEstavel = HIGH;
unsigned long ultimoDebounceBotao = 0;

// ===================== WIEGAND =====================
portMUX_TYPE muxWiegand = portMUX_INITIALIZER_UNLOCKED;

volatile uint64_t wiegandData = 0;
volatile uint8_t wiegandBits = 0;
volatile unsigned long ultimoPulsoWiegandUs = 0;
volatile bool overflowWiegand = false;
volatile unsigned long bloquearWiegandAteUs = 0;

uint64_t ultimoCartaoLido = 0;
unsigned long horarioUltimoCartaoLido = 0;
unsigned long inicioLeituraMestre = 0;
bool mestreEmLeitura = false;

// ===================== MEMORIA =====================
const char* NAMESPACE = "rfid";
const char* KEY_MASTER = "master";
const char* KEY_COUNT = "count";
const int MAX_CARTOES = 80;


// ===================== WIFI, HORARIO NTP E LOGS OFFLINE =====================
const unsigned long INTERVALO_ENVIO_LOG_MS = 250;
const unsigned long INTERVALO_RECONEXAO_WIFI_MS = 15000;
const unsigned long TEMPO_MAXIMO_TENTATIVA_WIFI_MS = 20000;
const char* ARQUIVO_LOGS_PENDENTES = "/logs_pendentes.txt";
const char* ARQUIVO_LOGS_TEMPORARIO = "/logs_temp.txt";
const char* ARQUIVO_MARCO_HORARIO_A = "/hora_a.txt";
const char* ARQUIVO_MARCO_HORARIO_B = "/hora_b.txt";
const unsigned long INTERVALO_MARCO_HORARIO_MS = 60000UL;
const size_t TAMANHO_MAXIMO_ARQUIVO_LOGS = 1024UL * 1024UL;

bool horarioSincronizado = false;
// Somente RTC valido ou sincronizacao NTP tornam a hora confiavel.
// O ultimo horario salvo e exibido como ESTIMADO, nunca enviado como horario real.
volatile bool horarioConfiavel = false;
bool horarioEstimadoRestaurado = false;
unsigned long ultimoMarcoHorarioMs = 0;
uint32_t ultimaSequenciaMarco = 0;
time_t ultimoMarcoEpoch = 0;
time_t marcoEpochNaInicializacao = 0;
String arquivoLogProvisorioAtual;
volatile bool temLogProvisorioAtual = false;
bool ntpConfigurado = false;
bool rtcDisponivel = false;
volatile bool ntpSincronizacaoPendente = false;
bool littleFsDisponivel = false;
bool wifiTentativaEmAndamento = false;
unsigned long ultimoEnvioLogMs = 0;
unsigned long ultimaTentativaWifiMs = 0;
unsigned long ultimaVerificacaoHorarioMs = 0;
const unsigned long INTERVALO_VERIFICACAO_HORARIO_MS = 5000;
const time_t EPOCH_MINIMO_VALIDO = 1704067200;
const long FUSO_HORARIO_SEGUNDOS = -3L * 3600L;
const int HORARIO_VERAO_SEGUNDOS = 0;
const char* SERVIDOR_NTP_1 = "pool.ntp.org";
const char* SERVIDOR_NTP_2 = "time.google.com";
const char* SERVIDOR_NTP_3 = "time.cloudflare.com";

struct LogPendente {
  uint32_t epoch;
  String dataEvento;
  String horaEvento;
  String evento;
  String cartao;
  String nome;
  String status;
  String observacao;
};

struct LogSemHorario {
  uint64_t tempoLigadoMs;
  String evento;
  String cartao;
  String nome;
  String status;
  String observacao;
};

uint64_t tempoLigadoMs() {
  return static_cast<uint64_t>(esp_timer_get_time() / 1000LL);
}

String inteiro64Texto(uint64_t valor) {
  char buffer[24];
  snprintf(buffer, sizeof(buffer), "%llu", static_cast<unsigned long long>(valor));
  return String(buffer);
}


String codigoCartaoHex(uint64_t codigo) {
  char buffer[17];
  snprintf(buffer, sizeof(buffer), "%08lX", (unsigned long)(codigo & 0xFFFFFFFF));
  return String(buffer);
}

String urlEncode(String valor) {
  String resultado = "";
  const char* hex = "0123456789ABCDEF";
  for (size_t i = 0; i < valor.length(); i++) {
    char c = valor.charAt(i);
    if (isalnum(c) || c == '-' || c == '_' || c == '.' || c == '~') resultado += c;
    else if (c == ' ') resultado += "%20";
    else { resultado += '%'; resultado += hex[(c >> 4) & 0x0F]; resultado += hex[c & 0x0F]; }
  }
  return resultado;
}

String limparCampoLog(String valor) {
  valor.replace("\r", " ");
  valor.replace("\n", " ");
  valor.replace("|", "/");
  return valor;
}

String formatarDataLocal(const struct tm &agora) {
  char buffer[11];
  strftime(buffer, sizeof(buffer), "%Y-%m-%d", &agora);
  return String(buffer);
}

String formatarHoraLocal(const struct tm &agora) {
  char buffer[9];
  strftime(buffer, sizeof(buffer), "%H:%M:%S", &agora);
  return String(buffer);
}

// ===================== MARCO DE HORA PERSISTENTE (LITTLEFS) =====================
// Dois arquivos alternados reduzem a chance de perder o ultimo marco em queda durante a escrita.
// Cada arquivo guarda "sequencia|epochUTC". Somente horario confirmado e gravado.
bool lerMarcoDeArquivo(const char* caminho, uint32_t &sequencia, time_t &epoch) {
  File arquivo = LittleFS.open(caminho, FILE_READ);
  if (!arquivo) return false;
  String linha = arquivo.readStringUntil('\n');
  arquivo.close();
  linha.trim();
  int separador = linha.indexOf('|');
  if (separador <= 0) return false;

  String textoSequencia = linha.substring(0, separador);
  String textoEpoch = linha.substring(separador + 1);
  char* fimSequencia = nullptr;
  char* fimEpoch = nullptr;
  unsigned long seq = strtoul(textoSequencia.c_str(), &fimSequencia, 10);
  long long segundos = strtoll(textoEpoch.c_str(), &fimEpoch, 10);
  if (!fimSequencia || *fimSequencia || !fimEpoch || *fimEpoch ||
      seq == 0 || segundos < static_cast<long long>(EPOCH_MINIMO_VALIDO) ||
      segundos >= 4102444800LL) return false;

  sequencia = static_cast<uint32_t>(seq);
  epoch = static_cast<time_t>(segundos);
  return true;
}

void carregarMarcoHorario() {
  if (!littleFsDisponivel) return;
  uint32_t seqA = 0, seqB = 0;
  time_t epochA = 0, epochB = 0;
  bool validoA = lerMarcoDeArquivo(ARQUIVO_MARCO_HORARIO_A, seqA, epochA);
  bool validoB = lerMarcoDeArquivo(ARQUIVO_MARCO_HORARIO_B, seqB, epochB);
  if (!validoA && !validoB) {
    Serial.println("HORA_CHECKPOINT | Nenhuma referencia persistente valida encontrada.");
    return;
  }

  if (validoB && (!validoA || seqB > seqA)) {
    ultimaSequenciaMarco = seqB;
    ultimoMarcoEpoch = epochB;
  } else {
    ultimaSequenciaMarco = seqA;
    ultimoMarcoEpoch = epochA;
  }
  marcoEpochNaInicializacao = ultimoMarcoEpoch;

  struct tm local;
  localtime_r(&ultimoMarcoEpoch, &local);
  Serial.print("HORA_CHECKPOINT | Ultimo horario confirmado salvo: ");
  Serial.print(formatarDataLocal(local));
  Serial.print(" ");
  Serial.print(formatarHoraLocal(local));
  Serial.println(" (pode estar atrasado ate 60 segundos antes da queda)");

  if (horarioConfiavel) return; // RTC forneceu hora valida; nao sobrescrever.

  struct timeval valor = {ultimoMarcoEpoch, 0};
  if (settimeofday(&valor, nullptr) == 0) {
    horarioEstimadoRestaurado = true;
    Serial.println("HORA_ESTIMADA | Relogio do ESP recuperado do LittleFS. Tempo sem energia DESCONHECIDO; logs serao provisorios.");
  } else {
    Serial.println("HORA_ESTIMADA_ERRO | Falha ao restaurar referencia no ESP.");
  }
}

bool salvarMarcoHorario(bool forcar = false) {
  if (!littleFsDisponivel || !horarioConfiavel || mutexFilaLogs == NULL) return false;
  if (!forcar && millis() - ultimoMarcoHorarioMs < INTERVALO_MARCO_HORARIO_MS) return false;
  time_t epoch = time(nullptr);
  if (epoch < EPOCH_MINIMO_VALIDO) return false;
  if (xSemaphoreTake(mutexFilaLogs, pdMS_TO_TICKS(200)) != pdTRUE) return false;

  uint32_t novaSequencia = ultimaSequenciaMarco + 1;
  if (novaSequencia == 0) novaSequencia = 1;
  const char* caminho = (novaSequencia % 2 == 0) ? ARQUIVO_MARCO_HORARIO_A : ARQUIVO_MARCO_HORARIO_B;
  File arquivo = LittleFS.open(caminho, FILE_WRITE);
  bool gravado = false;
  if (arquivo) {
    String linha = String(novaSequencia) + "|" + inteiro64Texto(static_cast<uint64_t>(epoch));
    gravado = arquivo.print(linha + "\n") == linha.length() + 1;
    arquivo.flush();
    arquivo.close();
  }
  xSemaphoreGive(mutexFilaLogs);
  if (gravado) {
    ultimaSequenciaMarco = novaSequencia;
    ultimoMarcoEpoch = epoch;
    ultimoMarcoHorarioMs = millis();
    if (forcar) Serial.println("HORA_CHECKPOINT_SALVO | Referencia confiavel armazenada no LittleFS.");
  } else {
    Serial.println("HORA_CHECKPOINT_ERRO | Falha ao gravar horario no LittleFS.");
  }
  return gravado;
}

void criarArquivoProvisorioInicializacao() {
  if (!littleFsDisponivel) return;
  char caminho[32];
  do {
    snprintf(caminho, sizeof(caminho), "/prov_%08lX%08lX.txt",
             static_cast<unsigned long>(esp_random()), static_cast<unsigned long>(esp_random()));
  } while (LittleFS.exists(caminho));
  arquivoLogProvisorioAtual = String(caminho);

  // Provisorios de inicializacoes anteriores sao preservados, mas NAO podem
  // ser datados apenas pelo NTP atual: nao sabemos a duracao das quedas antigas.
  File raiz = LittleFS.open("/");
  if (!raiz || !raiz.isDirectory()) return;
  unsigned int antigos = 0;
  File arquivo = raiz.openNextFile();
  while (arquivo) {
    String nome = String(arquivo.name());
    if (nome.startsWith("/prov_") || nome.startsWith("prov_")) antigos++;
    arquivo.close();
    arquivo = raiz.openNextFile();
  }
  raiz.close();
  if (antigos > 0) {
    Serial.printf("LOG_SEM_HORARIO_ANTERIOR | %u arquivo(s) preservado(s); nao enviar com data inventada.\n", antigos);
  }
}

void relatarTempoSemEnergia(time_t epochNtp) {
  if (!horarioEstimadoRestaurado || marcoEpochNaInicializacao < EPOCH_MINIMO_VALIDO) return;
  horarioEstimadoRestaurado = false; // Mostra apenas na primeira sincronizacao.
  int64_t segundos = static_cast<int64_t>(epochNtp) - static_cast<int64_t>(marcoEpochNaInicializacao)
                   - static_cast<int64_t>(tempoLigadoMs() / 1000ULL);
  if (segundos < 0) segundos = 0;
  unsigned long horas = static_cast<unsigned long>(segundos / 3600);
  unsigned long minutos = static_cast<unsigned long>((segundos % 3600) / 60);
  unsigned long restantes = static_cast<unsigned long>(segundos % 60);
  Serial.printf("TEMPO_SEM_ENERGIA_ESTIMADO | %luh %lum %lus; incerteza minima ate 60s (maior se houve mais reinicializacoes).\n",
                horas, minutos, restantes);
}

// ===================== RTC DS3231: HORA UTC NA MEMORIA, LOCAL BAHIA NOS LOGS =====================
uint8_t decimalParaBcd(uint8_t valor) {
  return ((valor / 10) << 4) | (valor % 10);
}

uint8_t bcdParaDecimal(uint8_t valor) {
  return ((valor >> 4) * 10) + (valor & 0x0F);
}

bool lerBytesRtc(uint8_t registrador, uint8_t *destino, uint8_t quantidade) {
  if (!rtcDisponivel) return false;
  Wire.beginTransmission(ENDERECO_RTC_DS3231);
  Wire.write(registrador);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(ENDERECO_RTC_DS3231, quantidade) != quantidade) return false;
  for (uint8_t i = 0; i < quantidade; i++) destino[i] = Wire.read();
  return true;
}

bool lerEpochRtc(time_t &epoch) {
  uint8_t status = 0;
  uint8_t campos[7];
  if (!lerBytesRtc(0x0F, &status, 1) || !lerBytesRtc(0x00, campos, 7)) return false;
  // OSF ligado significa oscilador parado em algum momento: hora nao e confiavel.
  if ((status & 0x80) || (campos[2] & 0x40)) return false;

  int segundo = bcdParaDecimal(campos[0] & 0x7F);
  int minuto  = bcdParaDecimal(campos[1] & 0x7F);
  int hora    = bcdParaDecimal(campos[2] & 0x3F);
  int dia     = bcdParaDecimal(campos[4] & 0x3F);
  int mes     = bcdParaDecimal(campos[5] & 0x1F);
  int ano     = 2000 + bcdParaDecimal(campos[6]);
  if ((campos[5] & 0x80) || ano < 2024 || segundo > 59 || minuto > 59 ||
      hora > 23 || dia < 1 || dia > 31 || mes < 1 || mes > 12) return false;

  // Conversao UTC sem timegm(): compativel com compiladores ESP32 que nao expõem essa funcao.
  // O DS3231 guarda UTC; nenhuma correcao de fuso deve ser aplicada nesta conversao.
  const uint8_t diasMes[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
  int64_t diasDesde1970 = 0;
  for (int y = 1970; y < ano; ++y) {
    const bool bissexto = (y % 4 == 0) && ((y % 100 != 0) || (y % 400 == 0));
    diasDesde1970 += bissexto ? 366 : 365;
  }
  for (int m = 1; m < mes; ++m) {
    diasDesde1970 += diasMes[m - 1];
    if (m == 2 && (ano % 4 == 0) && ((ano % 100 != 0) || (ano % 400 == 0))) {
      ++diasDesde1970;
    }
  }
  diasDesde1970 += dia - 1;
  const int64_t segundosUtc = diasDesde1970 * 86400LL + hora * 3600LL + minuto * 60LL + segundo;
  time_t candidato = static_cast<time_t>(segundosUtc);
  struct tm verificacaoUtc;
  if (candidato < EPOCH_MINIMO_VALIDO || !gmtime_r(&candidato, &verificacaoUtc) ||
      verificacaoUtc.tm_year != ano - 1900 || verificacaoUtc.tm_mon != mes - 1 ||
      verificacaoUtc.tm_mday != dia) return false;

  epoch = candidato;
  return true;
}

bool gravarEpochRtc(time_t epoch) {
  if (!rtcDisponivel || epoch < EPOCH_MINIMO_VALIDO) return false;
  struct tm utc;
  if (!gmtime_r(&epoch, &utc) || utc.tm_year + 1900 > 2099) return false;

  Wire.beginTransmission(ENDERECO_RTC_DS3231);
  Wire.write(0x00);
  Wire.write(decimalParaBcd(utc.tm_sec));
  Wire.write(decimalParaBcd(utc.tm_min));
  Wire.write(decimalParaBcd(utc.tm_hour)); // Forca modo 24 horas.
  Wire.write(decimalParaBcd(utc.tm_wday + 1));
  Wire.write(decimalParaBcd(utc.tm_mday));
  Wire.write(decimalParaBcd(utc.tm_mon + 1));
  Wire.write(decimalParaBcd((utc.tm_year + 1900) - 2000));
  if (Wire.endTransmission() != 0) return false;

  uint8_t status = 0;
  if (!lerBytesRtc(0x0F, &status, 1)) return false;
  Wire.beginTransmission(ENDERECO_RTC_DS3231);
  Wire.write(0x0F);
  Wire.write(status & ~0x80); // Limpa apenas a flag OSF apos acerto valido.
  if (Wire.endTransmission() != 0) return false;

  time_t conferido;
  return lerEpochRtc(conferido) && labs(static_cast<long>(conferido - epoch)) <= 2;
}

// Diagnostico somente leitura: NAO altera configuracao nem apaga o OSF.
// DS3231: controle 0x0E bit7=EOSC (1: oscilador para na bateria),
// status 0x0F bit7=OSF (1: oscilador parou e horario nao e confiavel).
void imprimirDiagnosticoRtc() {
  Serial.println("RTC_DIAG | INICIO (somente leitura, nao altera o DS3231)");
  if (!rtcDisponivel) {
    Serial.println("RTC_DIAG | ERRO=DS3231_NAO_DETECTADO (SDA=25 SCL=26)");
    return;
  }

  uint8_t controle = 0;
  uint8_t status = 0;
  uint8_t campos[7] = {};
  bool leituraControle = lerBytesRtc(0x0E, &controle, 1);
  bool leituraStatus = lerBytesRtc(0x0F, &status, 1);
  bool leituraHorario = lerBytesRtc(0x00, campos, 7);

  if (!leituraControle || !leituraStatus || !leituraHorario) {
    Serial.print("RTC_DIAG | ERRO=LEITURA_I2C CONTROLE=");
    Serial.print(leituraControle ? "OK" : "FALHA");
    Serial.print(" STATUS=");
    Serial.print(leituraStatus ? "OK" : "FALHA");
    Serial.print(" HORARIO=");
    Serial.println(leituraHorario ? "OK" : "FALHA");
    return;
  }

  const bool eosc = (controle & 0x80) != 0;
  const bool osf = (status & 0x80) != 0;
  const bool modo12Horas = (campos[2] & 0x40) != 0;
  Serial.printf("RTC_DIAG | CONTROLE=0x%02X EOSC=%u OSCILADOR_NA_BATERIA=%s\n",
                (unsigned)controle, (unsigned)eosc, eosc ? "DESLIGADO" : "HABILITADO");
  Serial.printf("RTC_DIAG | STATUS=0x%02X OSF=%u OSCILADOR_INTERROMPIDO=%s\n",
                (unsigned)status, (unsigned)osf, osf ? "SIM" : "NAO");
  Serial.printf("RTC_DIAG | REGISTROS_HORA=0x%02X,0x%02X,0x%02X,0x%02X,0x%02X,0x%02X,0x%02X\n",
                (unsigned)campos[0], (unsigned)campos[1], (unsigned)campos[2],
                (unsigned)campos[3], (unsigned)campos[4], (unsigned)campos[5], (unsigned)campos[6]);
  Serial.printf("RTC_DIAG | HORA_BRUTA_UTC=%02u:%02u:%02u DATA_BRUTA_UTC=%02u/%02u/20%02u MODO_12H=%u\n",
                (unsigned)bcdParaDecimal(campos[2] & 0x3F),
                (unsigned)bcdParaDecimal(campos[1] & 0x7F),
                (unsigned)bcdParaDecimal(campos[0] & 0x7F),
                (unsigned)bcdParaDecimal(campos[4] & 0x3F),
                (unsigned)bcdParaDecimal(campos[5] & 0x1F),
                (unsigned)bcdParaDecimal(campos[6]), (unsigned)modo12Horas);

  if (eosc) Serial.println("RTC_DIAG | ALERTA=EOSC_1 (oscilador configurado para parar na bateria)");
  if (osf) Serial.println("RTC_DIAG | ALERTA=OSF_1 (oscilador parou; conferir bateria, contatos e EOSC)");
  if (modo12Horas) Serial.println("RTC_DIAG | ALERTA=MODO_12H (firmware espera modo 24 horas)");

  time_t epochRtc;
  if (!lerEpochRtc(epochRtc)) {
    Serial.println("RTC_DIAG | VALIDACAO=REPROVADA (nao utilizar hora RTC para logs)");
  } else {
    struct tm horaLocal;
    localtime_r(&epochRtc, &horaLocal);
    Serial.print("RTC_DIAG | VALIDACAO=OK HORA_BAHIA=");
    Serial.print(formatarDataLocal(horaLocal));
    Serial.print(" ");
    Serial.println(formatarHoraLocal(horaLocal));
  }
  Serial.println("RTC_DIAG | FIM");
}

void iniciarRtcDs3231() {
  Wire.begin(PIN_RTC_SDA, PIN_RTC_SCL);
  Wire.setClock(100000);
  Wire.beginTransmission(ENDERECO_RTC_DS3231);
  rtcDisponivel = (Wire.endTransmission() == 0);
  if (!rtcDisponivel) {
    Serial.println("RTC_ERRO | DS3231 nao encontrado em SDA=25/SCL=26. NTP permanece ativo.");
    return;
  }

  time_t epochRtc;
  if (!lerEpochRtc(epochRtc)) {
    Serial.println("RTC_AGUARDANDO_NTP | DS3231 detectado, mas horario ainda nao e confiavel.");
    imprimirDiagnosticoRtc();
    return;
  }

  struct timeval valor = {epochRtc, 0};
  if (settimeofday(&valor, nullptr) != 0) {
    Serial.println("RTC_ERRO | Nao foi possivel restaurar hora do ESP32.");
    return;
  }

  horarioSincronizado = true;
  horarioConfiavel = true; // Somente porque a leitura RTC passou por OSF e validacao.
  struct tm horaLocal;
  localtime_r(&epochRtc, &horaLocal);
  Serial.print("RTC_OK | Relogio restaurado: ");
  Serial.print(formatarDataLocal(horaLocal));
  Serial.print(" ");
  Serial.println(formatarHoraLocal(horaLocal));
}

void aoSincronizarNtp(struct timeval *agora) {
  if (agora != nullptr && agora->tv_sec >= EPOCH_MINIMO_VALIDO) {
    ntpSincronizacaoPendente = true;
  }
}

void imprimirRtcStatus() {
  if (!rtcDisponivel) {
    Serial.println("RTC_ERRO | DS3231 nao detectado, confira SDA=25 SCL=26 VCC=3V3 e GND.");
    return;
  }
  time_t epochRtc;
  if (!lerEpochRtc(epochRtc)) {
    Serial.println("RTC_AGUARDANDO_NTP | DS3231 presente, mas sem hora valida. Conecte o Wi-Fi.");
    return;
  }
  struct tm horaLocal;
  localtime_r(&epochRtc, &horaLocal);
  Serial.print("RTC_OK | ");
  Serial.print(formatarDataLocal(horaLocal));
  Serial.print(" ");
  Serial.println(formatarHoraLocal(horaLocal));
}

bool obterHorarioAtual(time_t &epoch, struct tm &agoraLocal) {
  epoch = time(nullptr);

  if (!horarioConfiavel || epoch < EPOCH_MINIMO_VALIDO) {
    horarioSincronizado = false;
    return false;
  }

  localtime_r(&epoch, &agoraLocal);
  horarioSincronizado = true;
  return true;
}

void configurarNtp() {
  if (ntpConfigurado) {
    return;
  }

  sntp_set_time_sync_notification_cb(aoSincronizarNtp);
  configTime(
    FUSO_HORARIO_SEGUNDOS,
    HORARIO_VERAO_SEGUNDOS,
    SERVIDOR_NTP_1,
    SERVIDOR_NTP_2,
    SERVIDOR_NTP_3
  );

  ntpConfigurado = true;
  Serial.println("NTP_CONFIGURADO | Aguardando sincronizacao de data e hora.");
}

void atualizarHorarioNtp() {
  // Esta flag e ativada somente pelo retorno real de sincronizacao SNTP.
  if (ntpSincronizacaoPendente) {
    ntpSincronizacaoPendente = false;
    time_t epochNtp;
    struct tm agoraLocal;
    // A notificacao SNTP e a unica origem de confianca quando o RTC perdeu a hora.
    epochNtp = time(nullptr);
    if (epochNtp >= EPOCH_MINIMO_VALIDO) {
      horarioConfiavel = true;
    }
    if (obterHorarioAtual(epochNtp, agoraLocal)) {
      relatarTempoSemEnergia(epochNtp);
      Serial.print("NTP_OK | ");
      Serial.print(formatarDataLocal(agoraLocal));
      Serial.print(" ");
      Serial.println(formatarHoraLocal(agoraLocal));
      if (rtcDisponivel) {
        Serial.println(gravarEpochRtc(epochNtp) ?
          "RTC_SINCRONIZADO | DS3231 atualizado pelo NTP." :
          "RTC_ERRO | Falha ao atualizar DS3231 pelo NTP.");
      }
      salvarMarcoHorario(true);
    }
  }

  if (WiFi.status() != WL_CONNECTED) return;
  configurarNtp();

  if (millis() - ultimaVerificacaoHorarioMs < INTERVALO_VERIFICACAO_HORARIO_MS) return;
  ultimaVerificacaoHorarioMs = millis();

  bool estavaSincronizado = horarioSincronizado;
  time_t epoch;
  struct tm agoraLocal;
  if (!obterHorarioAtual(epoch, agoraLocal)) {
    if (estavaSincronizado) Serial.println("HORARIO_ALERTA | Horario do sistema ficou invalido.");
    return;
  }

  if (!estavaSincronizado) {
    Serial.print("HORARIO_OK | ");
    Serial.print(formatarDataLocal(agoraLocal));
    Serial.print(" ");
    Serial.println(formatarHoraLocal(agoraLocal));
  }
}

void iniciarLittleFs() {
  littleFsDisponivel = LittleFS.begin(true);

  if (!littleFsDisponivel) {
    Serial.println("LITTLEFS_ERRO | Nao foi possivel montar a memoria de logs.");
    return;
  }

  Serial.println("LITTLEFS_OK | Memoria permanente de logs pronta.");
  carregarMarcoHorario();
  criarArquivoProvisorioInicializacao();
  if (horarioConfiavel) salvarMarcoHorario(true); // Hora valida pelo RTC no boot.
}

void conectarWifi() {
  if (strlen(WIFI_SSID) == 0 || String(WIFI_SSID) == "COLOQUE_AQUI_O_NOME_DO_WIFI") {
    wifiConectado = false;
    wifiTentativaEmAndamento = false;
    return;
  }

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_SENHA);
  ultimaTentativaWifiMs = millis();
  wifiTentativaEmAndamento = true;
  Serial.println("Wi-Fi: conexao iniciada em segundo plano.");
}

void atualizarWifi() {
  if (WiFi.status() == WL_CONNECTED) {
    wifiTentativaEmAndamento = false;

    if (!wifiConectado) {
      wifiConectado = true;
      Serial.print("Wi-Fi conectado. IP: ");
      Serial.println(WiFi.localIP());
      configurarNtp();
    }
    return;
  }

  wifiConectado = false;

  if (wifiTentativaEmAndamento) {
    if (millis() - ultimaTentativaWifiMs < TEMPO_MAXIMO_TENTATIVA_WIFI_MS) {
      return;
    }

    WiFi.disconnect();
    wifiTentativaEmAndamento = false;
    Serial.println("Wi-Fi: tentativa expirou. Nova tentativa sera realizada.");
  }

  if (millis() - ultimaTentativaWifiMs >= INTERVALO_RECONEXAO_WIFI_MS) {
    conectarWifi();
  }
}

String serializarLog(const LogPendente &log) {
  String linha;
  linha.reserve(220);
  linha += String(log.epoch);
  linha += "|" + limparCampoLog(log.dataEvento);
  linha += "|" + limparCampoLog(log.horaEvento);
  linha += "|" + limparCampoLog(log.evento);
  linha += "|" + limparCampoLog(log.cartao);
  linha += "|" + limparCampoLog(log.nome);
  linha += "|" + limparCampoLog(log.status);
  linha += "|" + limparCampoLog(log.observacao);
  return linha;
}

bool desserializarLog(String linha, LogPendente &log) {
  linha.trim();
  String campos[8];
  int inicio = 0;

  for (int i = 0; i < 7; i++) {
    int separador = linha.indexOf('|', inicio);
    if (separador < 0) return false;
    campos[i] = linha.substring(inicio, separador);
    inicio = separador + 1;
  }

  campos[7] = linha.substring(inicio);
  log.epoch = strtoul(campos[0].c_str(), NULL, 10);
  log.dataEvento = campos[1];
  log.horaEvento = campos[2];
  log.evento = campos[3];
  log.cartao = campos[4];
  log.nome = campos[5];
  log.status = campos[6];
  log.observacao = campos[7];
  return log.epoch > 0 && log.evento.length() > 0;
}

// ===================== LOGS SEM HORA: ARQUIVO EXCLUSIVO DESTA INICIALIZACAO =====================
String serializarLogSemHorario(const LogSemHorario &log) {
  String linha = inteiro64Texto(log.tempoLigadoMs);
  linha += "|" + limparCampoLog(log.evento);
  linha += "|" + limparCampoLog(log.cartao);
  linha += "|" + limparCampoLog(log.nome);
  linha += "|" + limparCampoLog(log.status);
  linha += "|" + limparCampoLog(log.observacao);
  return linha;
}

bool desserializarLogSemHorario(String linha, LogSemHorario &log) {
  linha.trim();
  String campos[6];
  int inicio = 0;
  for (int i = 0; i < 5; ++i) {
    int separador = linha.indexOf('|', inicio);
    if (separador < 0) return false;
    campos[i] = linha.substring(inicio, separador);
    inicio = separador + 1;
  }
  campos[5] = linha.substring(inicio);
  char* fim = nullptr;
  unsigned long long valor = strtoull(campos[0].c_str(), &fim, 10);
  if (!fim || *fim || campos[1].length() == 0) return false;
  log.tempoLigadoMs = static_cast<uint64_t>(valor);
  log.evento = campos[1];
  log.cartao = campos[2];
  log.nome = campos[3];
  log.status = campos[4];
  log.observacao = campos[5];
  return true;
}

bool gravarLogProvisorio(String evento, String cartao, String nome, String status, String observacao) {
  if (arquivoLogProvisorioAtual.length() == 0) {
    Serial.println("LOG_SEM_HORARIO_ERRO | Caminho provisorio indisponivel.");
    return false;
  }
  LogSemHorario log = {tempoLigadoMs(), evento, cartao, nome, status, observacao};
  if (xSemaphoreTake(mutexFilaLogs, pdMS_TO_TICKS(100)) != pdTRUE) {
    Serial.println("LOG_MUTEX_OCUPADO | Provisorio nao gravado.");
    return false;
  }
  File arquivo = LittleFS.open(arquivoLogProvisorioAtual.c_str(), FILE_APPEND);
  if (!arquivo || arquivo.size() >= TAMANHO_MAXIMO_ARQUIVO_LOGS) {
    if (arquivo) arquivo.close();
    xSemaphoreGive(mutexFilaLogs);
    Serial.println("LOG_SEM_HORARIO_ERRO | Arquivo indisponivel ou cheio.");
    return false;
  }
  String linha = serializarLogSemHorario(log);
  bool salvo = arquivo.println(linha) > 0;
  arquivo.flush();
  arquivo.close();
  if (salvo) temLogProvisorioAtual = true;
  xSemaphoreGive(mutexFilaLogs);
  Serial.println(salvo ? "LOG_PROVISORIO_GRAVADO | Aguardando NTP; sem data inventada." :
                          "LOG_SEM_HORARIO_ERRO | Falha na persistencia do evento.");
  return salvo;
}

// Converte o tempo desde a inicializacao em UTC, ancorado na hora confirmada
// pelo NTP. Nunca estima a duracao de uma queda anterior de energia.
bool montarLogRecuperado(const LogSemHorario &provisorio,
                       const struct timeval &referencia, uint64_t tempoReferenciaMs,
                       LogPendente &confirmado) {
  if (provisorio.tempoLigadoMs > tempoReferenciaMs) return false;
  const int64_t decorridoMicros =
      static_cast<int64_t>(tempoReferenciaMs - provisorio.tempoLigadoMs) * 1000LL;
  const int64_t instanteMicros = static_cast<int64_t>(referencia.tv_sec) * 1000000LL +
                                 referencia.tv_usec - decorridoMicros;
  time_t epoch = static_cast<time_t>((instanteMicros + 500000LL) / 1000000LL);
  if (epoch < EPOCH_MINIMO_VALIDO || epoch > UINT32_MAX) return false;
  struct tm horaLocal;
  localtime_r(&epoch, &horaLocal);
  confirmado = {static_cast<uint32_t>(epoch), formatarDataLocal(horaLocal),
    formatarHoraLocal(horaLocal), provisorio.evento, provisorio.cartao,
    provisorio.nome, provisorio.status, provisorio.observacao};
  return true;
}

// So os eventos desta MESMA inicializacao podem ser corrigidos pelo NTP.
// Tempo de eventos de inicializacoes anteriores permanece separado no LittleFS.
void converterLogsProvisoriosDaInicializacao() {
  if (!littleFsDisponivel || !horarioConfiavel || !temLogProvisorioAtual ||
      arquivoLogProvisorioAtual.length() == 0) return;
  if (xSemaphoreTake(mutexFilaLogs, pdMS_TO_TICKS(200)) != pdTRUE) return;

  File origem = LittleFS.open(arquivoLogProvisorioAtual.c_str(), FILE_READ);
  if (!origem) {
    temLogProvisorioAtual = false;
    xSemaphoreGive(mutexFilaLogs);
    return;
  }

  struct timeval horaReferencia = {};
  gettimeofday(&horaReferencia, nullptr);
  const uint64_t uptimeReferencia = tempoLigadoMs();
  File destino = LittleFS.open(ARQUIVO_LOGS_PENDENTES, FILE_APPEND);
  if (!destino) {
    origem.close();
    xSemaphoreGive(mutexFilaLogs);
    Serial.println("LOG_RECUPERACAO_ERRO | Nao foi possivel abrir a fila confirmada.");
    return;
  }

  // Valida e calcula o tamanho exato ANTES de escrever na fila confirmada.
  // Se um item estiver corrompido, preserva todo o arquivo provisorio.
  size_t totalBytesNecessarios = 0;
  bool valido = true;
  while (origem.available()) {
    LogSemHorario provisorio;
    LogPendente confirmado;
    if (!desserializarLogSemHorario(origem.readStringUntil('\n'), provisorio) ||
        !montarLogRecuperado(provisorio, horaReferencia, uptimeReferencia, confirmado)) {
      valido = false;
      break;
    }
    totalBytesNecessarios += serializarLog(confirmado).length() + 2;
  }
  if (!valido || destino.size() + totalBytesNecessarios > TAMANHO_MAXIMO_ARQUIVO_LOGS) {
    origem.close(); destino.close(); xSemaphoreGive(mutexFilaLogs);
    Serial.println("LOG_RECUPERACAO_PENDENTE | Registro invalido ou falta espaco: mantido com horario desconhecido.");
    return;
  }

  origem.seek(0);
  unsigned int convertidos = 0;
  bool sucesso = true;
  while (origem.available()) {
    LogSemHorario provisorio;
    LogPendente confirmado;
    if (!desserializarLogSemHorario(origem.readStringUntil('\n'), provisorio) ||
        !montarLogRecuperado(provisorio, horaReferencia, uptimeReferencia, confirmado)) {
      sucesso = false;
      break;
    }
    String linha = serializarLog(confirmado);
    if (destino.print(linha + "\n") != linha.length() + 1) {
      sucesso = false;
      break;
    }
    ++convertidos;
  }
  destino.flush();
  destino.close();
  origem.close();
  if (sucesso) {
    LittleFS.remove(arquivoLogProvisorioAtual.c_str());
    temLogProvisorioAtual = false;
    Serial.printf("LOG_RECUPERADO_NTP | %u evento(s) convertidos com horario confirmado.\n", convertidos);
  } else {
    // Arquivo original e mantido para permitir diagnostico, sem apagar eventos.
    Serial.println("LOG_RECUPERACAO_ERRO | Arquivo provisorio preservado; verificar possiveis duplicatas antes de reenviar.");
  }
  xSemaphoreGive(mutexFilaLogs);
}

bool gravarLogPermanente(String evento, String cartao, String nome, String status, String observacao) {
  if (!littleFsDisponivel || mutexFilaLogs == NULL) {
    Serial.println("LOG_OFFLINE_INDISPONIVEL | LittleFS ou mutex nao inicializado.");
    return false;
  }

  time_t epoch;
  struct tm agoraLocal;
  if (!obterHorarioAtual(epoch, agoraLocal)) {
    // RTC invalido e sem NTP: NAO descarta o evento e NAO inventa horario.
    return gravarLogProvisorio(evento, cartao, nome, status, observacao);
  }

  if (xSemaphoreTake(mutexFilaLogs, pdMS_TO_TICKS(100)) != pdTRUE) {
    Serial.println("LOG_MUTEX_OCUPADO | Nao foi possivel gravar o log.");
    return false;
  }

  File arquivo = LittleFS.open(ARQUIVO_LOGS_PENDENTES, FILE_APPEND);
  if (!arquivo) {
    xSemaphoreGive(mutexFilaLogs);
    Serial.println("LOG_ARQUIVO_ERRO | Nao foi possivel abrir o arquivo de logs.");
    return false;
  }

  if (arquivo.size() >= TAMANHO_MAXIMO_ARQUIVO_LOGS) {
    arquivo.close();
    xSemaphoreGive(mutexFilaLogs);
    Serial.println("LOG_ARQUIVO_CHEIO | Limite de 1 MB atingido. Log nao gravado.");
    return false;
  }

  LogPendente log = {
    static_cast<uint32_t>(epoch),
    formatarDataLocal(agoraLocal),
    formatarHoraLocal(agoraLocal),
    evento,
    cartao,
    nome,
    status,
    observacao
  };

  bool gravado = arquivo.println(serializarLog(log)) > 0;
  arquivo.flush();
  arquivo.close();
  xSemaphoreGive(mutexFilaLogs);

  if (gravado) {
    Serial.print("LOG_GRAVADO | ");
    Serial.print(log.dataEvento);
    Serial.print(" ");
    Serial.print(log.horaEvento);
    Serial.print(" | ");
    Serial.println(evento);
  } else {
    Serial.println("LOG_GRAVACAO_ERRO | Falha ao persistir o evento.");
  }

  return gravado;
}

bool lerPrimeiroLogPendente(LogPendente &log) {
  if (!littleFsDisponivel || mutexFilaLogs == NULL) return false;
  if (xSemaphoreTake(mutexFilaLogs, pdMS_TO_TICKS(100)) != pdTRUE) return false;

  File arquivo = LittleFS.open(ARQUIVO_LOGS_PENDENTES, FILE_READ);
  if (!arquivo || !arquivo.available()) {
    if (arquivo) arquivo.close();
    xSemaphoreGive(mutexFilaLogs);
    return false;
  }

  String linha = arquivo.readStringUntil('\n');
  arquivo.close();
  xSemaphoreGive(mutexFilaLogs);
  return desserializarLog(linha, log);
}

bool removerPrimeiroLogPendente() {
  if (!littleFsDisponivel || mutexFilaLogs == NULL) return false;
  if (xSemaphoreTake(mutexFilaLogs, pdMS_TO_TICKS(200)) != pdTRUE) return false;

  File origem = LittleFS.open(ARQUIVO_LOGS_PENDENTES, FILE_READ);
  if (!origem) {
    xSemaphoreGive(mutexFilaLogs);
    return false;
  }

  origem.readStringUntil('\n');
  LittleFS.remove(ARQUIVO_LOGS_TEMPORARIO);
  File destino = LittleFS.open(ARQUIVO_LOGS_TEMPORARIO, FILE_WRITE);

  if (!destino) {
    origem.close();
    xSemaphoreGive(mutexFilaLogs);
    return false;
  }

  uint8_t buffer[256];
  while (origem.available()) {
    size_t lidos = origem.read(buffer, sizeof(buffer));
    if (lidos > 0) destino.write(buffer, lidos);
  }

  destino.flush();
  destino.close();
  origem.close();

  LittleFS.remove(ARQUIVO_LOGS_PENDENTES);
  bool renomeado = LittleFS.rename(ARQUIVO_LOGS_TEMPORARIO, ARQUIVO_LOGS_PENDENTES);
  xSemaphoreGive(mutexFilaLogs);
  return renomeado;
}

void enviarProximoLogDaFila() {
  if (WiFi.status() != WL_CONNECTED) return;
  if (millis() - ultimoEnvioLogMs < INTERVALO_ENVIO_LOG_MS) return;
  ultimoEnvioLogMs = millis();

  LogPendente log;
  if (!lerPrimeiroLogPendente(log)) return;

  WiFiClientSecure client;
  client.setInsecure();

  HTTPClient http;
  http.setConnectTimeout(10000);
  http.setTimeout(15000);
  http.setFollowRedirects(HTTPC_STRICT_FOLLOW_REDIRECTS);

  String url = String(URL_LOGS_GOOGLE_SHEETS);
  url += "?dispositivo=" + urlEncode(String(DISPOSITIVO_ID));
  url += "&epoch=" + String(log.epoch);
  url += "&data_evento=" + urlEncode(log.dataEvento);
  url += "&hora_evento=" + urlEncode(log.horaEvento);
  url += "&evento=" + urlEncode(log.evento);
  url += "&cartao=" + urlEncode(log.cartao);
  url += "&nome=" + urlEncode(log.nome);
  url += "&status=" + urlEncode(log.status);
  url += "&obs=" + urlEncode(log.observacao);

  if (!http.begin(client, url)) {
    Serial.println("LOG_ENVIO_FALHOU | Nao foi possivel iniciar a requisicao HTTP.");
    Serial.print("LOG_URL | ");
    Serial.println(url);
    return;
  }

  int codigoHttp = http.GET();

  if (codigoHttp >= 200 && codigoHttp < 400) {
    Serial.print("LOG_ENVIADO | HTTP ");
    Serial.print(codigoHttp);
    Serial.print(" | ");
    Serial.println(log.evento);

    if (!removerPrimeiroLogPendente()) {
      Serial.println("LOG_REMOCAO_ERRO | Evento enviado, mas nao removido do arquivo local.");
    }
  } else {
    Serial.print("LOG_ENVIO_FALHOU | HTTP ");
    Serial.println(codigoHttp);
    Serial.print("LOG_URL | ");
    Serial.println(url);
  }

  http.end();
}

void atualizarLogsOnline() {
  atualizarWifi();
  atualizarHorarioNtp();
  salvarMarcoHorario(false); // 60 segundos, somente com hora confiavel.
  converterLogsProvisoriosDaInicializacao();
  enviarProximoLogDaFila();
}

void tarefaLogsOnline(void *parametro) {
  for (;;) {
    atualizarLogsOnline();
    vTaskDelay(pdMS_TO_TICKS(50));
  }
}

void enviarLogGoogleSheets(String evento, String cartao, String nome, String status, String observacao) {
  gravarLogPermanente(evento, cartao, nome, status, observacao);
}

void registrarLog(String evento, uint64_t cartao, String status, String observacao) {
  enviarLogGoogleSheets(evento, cartao > 0 ? codigoCartaoHex(cartao) : "", "", status, observacao);
}

void registrarLogSimples(String evento, String status, String observacao) {
  enviarLogGoogleSheets(evento, "", "", status, observacao);
}

// ===================== FUNCOES BASICAS =====================
void inibirWiegandPorRuido() {
  portENTER_CRITICAL(&muxWiegand);
  bloquearWiegandAteUs = micros() + (TEMPO_BLOQUEIO_WIEGAND_APOS_RELE_MS * 1000UL);
  wiegandBits = 0;
  wiegandData = 0;
  overflowWiegand = false;
  ultimoPulsoWiegandUs = 0;
  portEXIT_CRITICAL(&muxWiegand);
}

void escreverRele(int pino, bool ligar) {
  if (pino == PIN_RELE_AUTORIZACAO) {
    estadoReleAutorizacao = ligar;
  }

  if (pino == PIN_RELE_COMANDO) {
    estadoReleComando = ligar;
  }

  if (RELE_ATIVO_EM_LOW) {
    digitalWrite(pino, ligar ? LOW : HIGH);
  } else {
    digitalWrite(pino, ligar ? HIGH : LOW);
  }

  inibirWiegandPorRuido();
}

void escreverLedStatus(bool ligar) {
  if (!HABILITAR_LED_STATUS) {
    estadoLedStatus = false;
    digitalWrite(PIN_LED_STATUS, LOW);
    return;
  }

  estadoLedStatus = ligar;
  digitalWrite(PIN_LED_STATUS, ligar ? HIGH : LOW);
}

void desligarSaidas() {
  escreverRele(PIN_RELE_AUTORIZACAO, false);
  escreverRele(PIN_RELE_COMANDO, false);
  escreverLedStatus(false);
}

bool lerBotaoPressionado() {
  return digitalRead(PIN_BOTAO_LIGA_DESLIGA) == LOW;
}

bool comandoRetidoLigado() {
  return estadoReleComando;
}

void acionarEmergencia() {
  if (emergenciaAtiva) {
    return;
  }

  emergenciaAtiva = true;
  maquinaLigada = false;
  autorizado = false;
  aguardandoRestart = false;

  escreverRele(PIN_RELE_AUTORIZACAO, false);
  escreverRele(PIN_RELE_COMANDO, false);
  escreverLedStatus(false);

  Serial.println("EMERGENCIA ACIONADA. Maquina desligada e nova autorizacao obrigatoria.");
  registrarLogSimples("EMERGENCIA_ACIONADA", "BLOQUEADO", "Maquina desligada pelo contato NF");
}

void liberarEmergencia() {
  if (!emergenciaAtiva) {
    return;
  }

  emergenciaAtiva = false;
  maquinaLigada = false;
  autorizado = false;
  aguardandoRestart = false;

  escreverRele(PIN_RELE_AUTORIZACAO, false);
  escreverRele(PIN_RELE_COMANDO, false);
  escreverLedStatus(false);

  Serial.println("EMERGENCIA LIBERADA. Novo cracha autorizado obrigatorio para liberar a partida.");
  registrarLogSimples("EMERGENCIA_LIBERADA", "BLOQUEADO", "Aguardando novo cracha autorizado");
}

void atualizarEmergencia() {
  bool leituraAtual = digitalRead(PIN_EMERGENCIA_NF);

  if (leituraAtual != ultimoEstadoEmergencia) {
    ultimoDebounceEmergencia = millis();
    ultimoEstadoEmergencia = leituraAtual;
  }

  if (millis() - ultimoDebounceEmergencia < TEMPO_DEBOUNCE_EMERGENCIA_MS) {
    return;
  }

  if (leituraAtual == estadoEmergenciaEstavel) {
    return;
  }

  estadoEmergenciaEstavel = leituraAtual;

  if (estadoEmergenciaEstavel == HIGH) {
    acionarEmergencia();
  } else {
    liberarEmergencia();
  }
}

// ===================== INTERRUPCOES WIEGAND =====================
void IRAM_ATTR registrarBitWiegand(uint8_t bitValue) {
  unsigned long agoraUs = micros();

  if ((long)(agoraUs - bloquearWiegandAteUs) < 0) {
    return;
  }

  portENTER_CRITICAL_ISR(&muxWiegand);

  if (wiegandBits >= 64) {
    overflowWiegand = true;
    ultimoPulsoWiegandUs = micros();
    portEXIT_CRITICAL_ISR(&muxWiegand);
    return;
  }

  wiegandData <<= 1;

  if (bitValue == 1) {
    wiegandData |= 1ULL;
  }

  wiegandBits++;
  ultimoPulsoWiegandUs = micros();

  portEXIT_CRITICAL_ISR(&muxWiegand);
}

void IRAM_ATTR isrD0() {
  registrarBitWiegand(0);
}

void IRAM_ATTR isrD1() {
  registrarBitWiegand(1);
}

bool bitsWiegandAceitos(uint8_t bits) {
  return bits == 26 || bits == 34 || bits == 35 || bits == 37;
}

uint64_t extrairCodigoWiegand(uint64_t rawData, uint8_t bits) {
  if (bits <= 2) {
    return rawData;
  }

  uint64_t semParidadeInicial = rawData & ((1ULL << (bits - 1)) - 1ULL);
  uint64_t semParidades = semParidadeInicial >> 1;
  return semParidades;
}

void limparBufferWiegand() {
  portENTER_CRITICAL(&muxWiegand);
  wiegandBits = 0;
  wiegandData = 0;
  overflowWiegand = false;
  ultimoPulsoWiegandUs = 0;
  portEXIT_CRITICAL(&muxWiegand);
}

bool obterCartao(uint64_t &codigo) {
  if ((long)(micros() - bloquearWiegandAteUs) < 0) {
    limparBufferWiegand();
    return false;
  }

  uint8_t bits = 0;
  uint64_t dados = 0;
  unsigned long ultimoPulso = 0;
  bool overflow = false;

  portENTER_CRITICAL(&muxWiegand);
  bits = wiegandBits;
  dados = wiegandData;
  ultimoPulso = ultimoPulsoWiegandUs;
  overflow = overflowWiegand;
  portEXIT_CRITICAL(&muxWiegand);

  if (bits == 0) {
    return false;
  }

  if ((micros() - ultimoPulso) < TEMPO_WIEGAND_FINAL_US) {
    return false;
  }

  limparBufferWiegand();

  if (overflow) {
    Serial.println("Leitura Wiegand ignorada: pacote maior que 64 bits.");
    return false;
  }

  if (!bitsWiegandAceitos(bits)) {
    Serial.print("Leitura Wiegand ignorada: quantidade de bits invalida = ");
    Serial.println(bits);
    return false;
  }

  codigo = extrairCodigoWiegand(dados, bits);

  Serial.print("Cartao lido: ");
  Serial.print((unsigned long)(codigo >> 32), HEX);
  Serial.println((unsigned long)(codigo & 0xFFFFFFFF), HEX);
  Serial.print("Bits Wiegand: ");
  Serial.println(bits);
  registrarLog("CARTAO_LIDO", codigo, "OK", "Bits Wiegand: " + String(bits));

  return true;
}

// ===================== MEMORIA DE CARTOES =====================
String chaveCartao(int indice) {
  return "card" + String(indice);
}

void carregarMestre() {
  cartaoMestre = CARTAO_MESTRE_FIXO;
  Serial.print("Cartao mestre fixo carregado: ");
  Serial.println((unsigned long)cartaoMestre, HEX);
}

void gravarMestre(uint64_t codigo) {
  cartaoMestre = CARTAO_MESTRE_FIXO;
  Serial.println("Cadastro automatico de mestre desativado. Mestre fixo mantido.");
}

int quantidadeCartoes() {
  prefs.begin(NAMESPACE, true);
  int count = prefs.getInt(KEY_COUNT, 0);
  prefs.end();
  return count;
}

uint64_t lerCartaoIndice(int indice) {
  prefs.begin(NAMESPACE, true);
  uint64_t codigo = prefs.getULong64(chaveCartao(indice).c_str(), 0);
  prefs.end();
  return codigo;
}

void gravarQuantidadeCartoes(int count) {
  prefs.begin(NAMESPACE, false);
  prefs.putInt(KEY_COUNT, count);
  prefs.end();
}

void gravarCartaoIndice(int indice, uint64_t codigo) {
  prefs.begin(NAMESPACE, false);
  prefs.putULong64(chaveCartao(indice).c_str(), codigo);
  prefs.end();
}

bool cartaoExiste(uint64_t codigo) {
  int count = quantidadeCartoes();

  for (int i = 0; i < count; i++) {
    if (lerCartaoIndice(i) == codigo) {
      return true;
    }
  }

  return false;
}

bool cadastrarCartao(uint64_t codigo) {
  if (codigo == cartaoMestre) {
    Serial.println("Cartao mestre nao pode ser cadastrado como usuario.");
    return false;
  }

  if (cartaoExiste(codigo)) {
    Serial.println("Cartao ja cadastrado.");
    return false;
  }

  int count = quantidadeCartoes();

  if (count >= MAX_CARTOES) {
    Serial.println("Limite de cartoes atingido.");
    return false;
  }

  gravarCartaoIndice(count, codigo);
  gravarQuantidadeCartoes(count + 1);

  Serial.println("Cartao cadastrado com sucesso.");
  registrarLog("CARTAO_CADASTRADO", codigo, "OK", "");
  return true;
}

bool removerCartao(uint64_t codigo) {
  if (codigo == cartaoMestre) {
    Serial.println("Cartao mestre nao pode ser removido.");
    return false;
  }

  int count = quantidadeCartoes();

  for (int i = 0; i < count; i++) {
    if (lerCartaoIndice(i) == codigo) {
      for (int j = i; j < count - 1; j++) {
        uint64_t proximo = lerCartaoIndice(j + 1);
        gravarCartaoIndice(j, proximo);
      }

      gravarCartaoIndice(count - 1, 0);
      gravarQuantidadeCartoes(count - 1);

      Serial.println("Cartao removido com sucesso.");
      registrarLog("CARTAO_REMOVIDO", codigo, "OK", "");
      return true;
    }
  }

  Serial.println("Cartao nao encontrado para remocao.");
  registrarLog("CARTAO_REMOVER_FALHA", codigo, "NAO_ENCONTRADO", "");
  return false;
}

// ===================== LOGICA DE ADMINISTRACAO =====================
void entrarModoAdmin() {
  modoAdmin = true;
  inicioModoAdmin = millis();
  Serial.println("Modo administrador ativo por 20 segundos.");
  registrarLogSimples("MODO_ADMIN_ON", "OK", "");
}

void sairModoAdmin() {
  modoAdmin = false;
  mestreEmLeitura = false;
  inicioLeituraMestre = 0;
  Serial.println("Modo administrador encerrado.");
  registrarLogSimples("MODO_ADMIN_OFF", "OK", "");
}

void tratarCartaoModoAdmin(uint64_t codigo) {
  if (codigo == cartaoMestre) {
    Serial.println("Cartao mestre ignorado no modo administrador.");
    return;
  }

  if (cartaoExiste(codigo)) {
    removerCartao(codigo);
  } else {
    cadastrarCartao(codigo);
  }

  sairModoAdmin();
}

void tratarCartaoMestre(uint64_t codigo) {
  if (codigo != cartaoMestre) {
    mestreEmLeitura = false;
    inicioLeituraMestre = 0;
    return;
  }

  mestreEmLeitura = false;
  inicioLeituraMestre = 0;
  Serial.println("Cartao mestre detectado. Modo administrador liberado para cadastrar ou descadastrar.");
  registrarLog("MESTRE_DETECTADO", codigo, "OK", "");
  entrarModoAdmin();
}

void atualizarLeituraMestre() {
  // Modo administrador agora entra imediatamente ao ler o cracha mestre.
}

// ===================== LOGICA DE AUTORIZACAO =====================
void autorizarPartida() {
  if (emergenciaAtiva) {
    Serial.println("Cartao reconhecido, mas a emergencia esta acionada. Partida bloqueada.");
    registrarLogSimples("AUTORIZACAO_BLOQUEADA_EMERGENCIA", "BLOQUEADO", "Liberar emergencia antes de autorizar");
    return;
  }

  autorizado = true;
  aguardandoRestart = false;
  inicioAutorizacao = millis();
  escreverRele(PIN_RELE_AUTORIZACAO, true);
  Serial.println("Cartao autorizado. Janela de partida aberta por 30 segundos.");
  registrarLogSimples("CARTAO_AUTORIZADO", "OK", "Janela de partida aberta");
}

void bloquearPartida() {
  autorizado = false;
  aguardandoRestart = false;
  escreverRele(PIN_RELE_AUTORIZACAO, false);
  escreverRele(PIN_RELE_COMANDO, false);
  Serial.println("Partida bloqueada. Necessario cracha autorizado.");
  registrarLogSimples("PARTIDA_BLOQUEADA", "BLOQUEADO", "Necessario cracha autorizado");
}

void iniciarJanelaRestart() {
  autorizado = true;
  aguardandoRestart = true;
  maquinaLigada = false;
  inicioRestart = millis();
  escreverRele(PIN_RELE_AUTORIZACAO, true);
  escreverRele(PIN_RELE_COMANDO, false);
  Serial.println("Maquina desligada pelo botao. Restart liberado por 30 segundos.");
  registrarLogSimples("MAQUINA_DESLIGADA", "OK", "Restart liberado");
}

bool leituraRepetidaMuitoRapida(uint64_t codigo) {
  if (codigo == cartaoMestre) {
    return false;
  }

  if (codigo != ultimoCartaoLido) {
    return false;
  }

  return millis() - horarioUltimoCartaoLido < TEMPO_RELEITURA_CARTAO_MS;
}

void tratarCartaoNormal(uint64_t codigo) {
  if (cartaoMestre == 0) {
    gravarMestre(codigo);
    return;
  }

  if (leituraRepetidaMuitoRapida(codigo)) {
    return;
  }

  if (codigo == cartaoMestre) {
    tratarCartaoMestre(codigo);

    if (PERMITIR_MESTRE_COMO_USUARIO_TESTE && !modoAdmin) {
      autorizarPartida();
      Serial.println("Modo teste: cartao mestre tambem liberou a partida.");
    }

    return;
  }

  mestreEmLeitura = false;
  inicioLeituraMestre = 0;

  if (cartaoExiste(codigo)) {
    autorizarPartida();
  } else {
    Serial.println("Cartao nao autorizado.");
    registrarLog("CARTAO_NEGADO", codigo, "NEGADO", "Cartao nao cadastrado");
  }
}

void tratarBotaoPressionado() {
  if (emergenciaAtiva) {
    Serial.println("Botao ignorado. Emergencia acionada.");
    registrarLogSimples("BOTAO_BLOQUEADO_EMERGENCIA", "BLOQUEADO", "Emergencia acionada");
    return;
  }

  if (comandoRetidoLigado()) {
    Serial.println("Botao pressionado. Desligando maquina pelo codigo.");
    iniciarJanelaRestart();
    return;
  }

  if (!autorizado) {
    Serial.println("Botao pressionado sem autorizacao. Ignorado.");
    registrarLogSimples("BOTAO_SEM_AUTORIZACAO", "IGNORADO", "");
    return;
  }

  Serial.println("Botao pressionado. Ligando maquina pelo codigo.");
  maquinaLigada = true;
  autorizado = true;
  aguardandoRestart = false;
  escreverRele(PIN_RELE_AUTORIZACAO, true);
  escreverRele(PIN_RELE_COMANDO, true);
  registrarLogSimples("MAQUINA_LIGADA", "OK", "Comando retido pelo codigo");
}

// ===================== LED DE STATUS =====================
void atualizarLedStatus() {
  static unsigned long ultimoPisca = 0;
  static bool estadoLed = false;

  maquinaLigada = comandoRetidoLigado();

  if (maquinaLigada) {
    escreverLedStatus(true);
    return;
  }

  if (modoAdmin) {
    if (millis() - ultimoPisca >= 150) {
      ultimoPisca = millis();
      estadoLed = !estadoLed;
      escreverLedStatus(estadoLed);
    }
    return;
  }

  if (autorizado) {
    if (millis() - ultimoPisca >= 500) {
      ultimoPisca = millis();
      estadoLed = !estadoLed;
      escreverLedStatus(estadoLed);
    }
    return;
  }

  escreverLedStatus(false);
}

// ===================== TEMPORIZADORES =====================
void atualizarTemporizadores() {
  maquinaLigada = comandoRetidoLigado();

  if (modoAdmin && millis() - inicioModoAdmin >= TEMPO_MODO_ADMIN_MS) {
    sairModoAdmin();
  }

  atualizarLeituraMestre();

  if (maquinaLigada) {
    return;
  }

  if (!autorizado && estadoReleComando) {
    escreverRele(PIN_RELE_COMANDO, false);
  }

  if (autorizado && !aguardandoRestart) {
    if (millis() - inicioAutorizacao >= TEMPO_AUTORIZACAO_MS) {
      bloquearPartida();
    }
  }

  if (autorizado && aguardandoRestart) {
    if (millis() - inicioRestart >= TEMPO_RESTART_MS) {
      bloquearPartida();
    }
  }
}

// ===================== LEITURA DO BOTAO =====================
void atualizarBotao() {
  bool leituraAtual = lerBotaoPressionado() ? LOW : HIGH;

  if (leituraAtual != ultimoEstadoBotao) {
    ultimoDebounceBotao = millis();
  }

  if ((millis() - ultimoDebounceBotao) > TEMPO_DEBOUNCE_BOTAO_MS) {
    if (leituraAtual != estadoBotaoEstavel) {
      estadoBotaoEstavel = leituraAtual;

      if (estadoBotaoEstavel == LOW) {
        tratarBotaoPressionado();
      }
    }
  }

  ultimoEstadoBotao = leituraAtual;
}


// ===================== MONITOR DAS ENTRADAS E SAIDAS =====================
unsigned long tempoRestanteMs(unsigned long inicio, unsigned long duracao) {
  unsigned long agora = millis();

  if (agora - inicio >= duracao) {
    return 0;
  }

  return duracao - (agora - inicio);
}

void imprimirEstadoSistema(const char* origem) {
  bool botaoPressionado = lerBotaoPressionado();
  bool comandoLigado = comandoRetidoLigado();

  Serial.println("========== MONITOR ==========");
  Serial.print("Origem: ");
  Serial.println(origem);

  Serial.print("Entrada GPIO32 Botao: ");
  Serial.println(botaoPressionado ? "PRESSIONADO" : "SOLTO");

  Serial.print("Estado interno da maquina por codigo: ");
  Serial.println(comandoLigado ? "LIGADA" : "DESLIGADA");

  Serial.print("Saida GPIO18 Rele autorizacao: ");
  Serial.print(estadoReleAutorizacao ? "LIGADO" : "DESLIGADO");
  Serial.print(" | Nivel GPIO: ");
  Serial.println(digitalRead(PIN_RELE_AUTORIZACAO) == HIGH ? "HIGH" : "LOW");

  Serial.print("Saida GPIO19 Rele comando retido: ");
  Serial.print(estadoReleComando ? "LIGADO" : "DESLIGADO");
  Serial.print(" | Nivel GPIO: ");
  Serial.println(digitalRead(PIN_RELE_COMANDO) == HIGH ? "HIGH" : "LOW");

  Serial.print("Saida GPIO21 LED status: ");
  if (!HABILITAR_LED_STATUS) {
    Serial.print("INIBIDO");
  } else {
    Serial.print(estadoLedStatus ? "LIGADO" : "DESLIGADO");
  }
  Serial.print(" | Nivel GPIO: ");
  Serial.println(digitalRead(PIN_LED_STATUS) == HIGH ? "HIGH" : "LOW");

  Serial.print("Autorizado: ");
  Serial.println(autorizado ? "SIM" : "NAO");

  Serial.print("Modo admin: ");
  Serial.println(modoAdmin ? "SIM" : "NAO");

  Serial.print("Aguardando restart: ");
  Serial.println(aguardandoRestart ? "SIM" : "NAO");

  if (!comandoLigado && autorizado && !aguardandoRestart) {
    Serial.print("Tempo restante autorizacao: ");
    Serial.print(tempoRestanteMs(inicioAutorizacao, TEMPO_AUTORIZACAO_MS) / 1000);
    Serial.println(" s");
  }

  if (!comandoLigado && autorizado && aguardandoRestart) {
    Serial.print("Tempo restante restart: ");
    Serial.print(tempoRestanteMs(inicioRestart, TEMPO_RESTART_MS) / 1000);
    Serial.println(" s");
  }

  if (modoAdmin) {
    Serial.print("Tempo restante modo admin: ");
    Serial.print(tempoRestanteMs(inicioModoAdmin, TEMPO_MODO_ADMIN_MS) / 1000);
    Serial.println(" s");
  }

  Serial.println("=============================");
}

void atualizarMonitorSerial() {
  if (!monitorSerialAtivo) {
    return;
  }

  if (millis() - ultimoMonitorSerial < TEMPO_MONITOR_SERIAL_MS) {
    return;
  }

  ultimoMonitorSerial = millis();
  imprimirEstadoSistema("AUTOMATICO");
}

// ===================== COMANDOS PELO SERIAL =====================
void apagarMemoriaRfid() {
  prefs.begin(NAMESPACE, false);
  prefs.clear();
  prefs.end();

  cartaoMestre = CARTAO_MESTRE_FIXO;
  autorizado = false;
  modoAdmin = false;
  maquinaLigada = false;
  aguardandoRestart = false;
  mestreEmLeitura = false;
  inicioLeituraMestre = 0;
  ultimoCartaoLido = 0;
  horarioUltimoCartaoLido = 0;

  desligarSaidas();

  if (emergenciaAtiva) {
    Serial.println("EMERGENCIA ATIVA NA INICIALIZACAO. Saidas mantidas desligadas.");
    registrarLogSimples("EMERGENCIA_ATIVA_INICIALIZACAO", "BLOQUEADO", "GPIO33 em HIGH na partida");
  }

  limparBufferWiegand();

  Serial.println("Memoria RFID apagada com sucesso.");
  registrarLogSimples("MEMORIA_RFID_APAGADA", "OK", "");
  Serial.println("Cartao mestre fixo mantido: 0E6242D.");
}

void tratarComandoSerial(String comando) {
  comando.trim();
  comando.toUpperCase();

  if (comando.length() == 0) {
    return;
  }

  if (aguardandoConfirmacaoReset) {
    if (comando == "SIM") {
      aguardandoConfirmacaoReset = false;
      apagarMemoriaRfid();
      return;
    }

    aguardandoConfirmacaoReset = false;
    Serial.println("Reset cancelado.");
    return;
  }

  if (comando == "RESET") {
    aguardandoConfirmacaoReset = true;
    inicioConfirmacaoReset = millis();
    Serial.println("Confirmar limpeza total da memoria RFID?");
    Serial.println("Digite SIM em ate 15 segundos para apagar mestre e cartoes.");
    return;
  }

  if (comando == "STATUS") {
    Serial.println("STATUS DO SISTEMA");
    Serial.print("Mestre gravado: ");
    Serial.println(cartaoMestre == 0 ? "NAO" : "SIM");
    Serial.print("Quantidade de cartoes cadastrados: ");
    Serial.println(quantidadeCartoes());
    Serial.print("Mestre libera maquina em modo teste: ");
    Serial.println(PERMITIR_MESTRE_COMO_USUARIO_TESTE ? "SIM" : "NAO");
    Serial.print("Codigo mestre fixo: ");
    Serial.println((unsigned long)cartaoMestre, HEX);
    imprimirEstadoSistema("STATUS");
    return;
  }

  if (comando == "RTC STATUS") {
    imprimirRtcStatus();
    return;
  }

  if (comando == "RTC DIAG") {
    imprimirDiagnosticoRtc();
    return;
  }

  if (comando == "HORA STATUS") {
    time_t agora = time(nullptr);
    struct tm local;
    localtime_r(&agora, &local);
    Serial.print("HORA_STATUS | FONTE=");
    Serial.println(horarioConfiavel ? "CONFIRMADA_RTC_OU_NTP" :
                   (horarioEstimadoRestaurado ? "LITTLEFS_ESTIMADA" : "SEM_HORA_CONFIAVEL"));
    if (agora >= EPOCH_MINIMO_VALIDO) {
      Serial.print("HORA_STATUS | RELOGIO_ESP=");
      Serial.print(formatarDataLocal(local));
      Serial.print(" ");
      Serial.println(formatarHoraLocal(local));
    }
    Serial.printf("HORA_STATUS | MARCO_EPOCH=%llu LOGS_PROVISORIOS_ATUAIS=%s\n",
      static_cast<unsigned long long>(ultimoMarcoEpoch), temLogProvisorioAtual ? "SIM" : "NAO");
    return;
  }

  if (comando == "MONITOR ON") {
    monitorSerialAtivo = true;
    ultimoMonitorSerial = 0;
    Serial.println("Monitor serial automatico ativado.");
    return;
  }

  if (comando == "MONITOR OFF") {
    monitorSerialAtivo = false;
    Serial.println("Monitor serial automatico desativado.");
    return;
  }

  Serial.println("Comando nao reconhecido.");
  Serial.println("Comandos disponiveis: RESET, STATUS, RTC STATUS, RTC DIAG, HORA STATUS, MONITOR ON, MONITOR OFF.");
}

void atualizarSerial() {
  if (aguardandoConfirmacaoReset && millis() - inicioConfirmacaoReset > TEMPO_CONFIRMACAO_RESET_MS) {
    aguardandoConfirmacaoReset = false;
    Serial.println("Tempo de confirmacao expirado. Reset cancelado.");
  }

  if (Serial.available() <= 0) {
    return;
  }

  String comando = Serial.readStringUntil('\n');
  tratarComandoSerial(comando);
}

// ===================== SETUP =====================
void setup() {
  Serial.begin(115200);

  // O RTC guarda UTC; os logs e o Monitor Serial mostram horario de Salvador/BA.
  setenv("TZ", "BRT3", 1);
  tzset();
  iniciarRtcDs3231();

  mutexFilaLogs = xSemaphoreCreateMutex();
  iniciarLittleFs();
  conectarWifi();

  pinMode(PIN_WIEGAND_D0, INPUT_PULLUP);
  pinMode(PIN_WIEGAND_D1, INPUT_PULLUP);

  pinMode(PIN_BOTAO_LIGA_DESLIGA, INPUT_PULLUP);
  pinMode(PIN_EMERGENCIA_NF, INPUT_PULLUP);

  ultimoEstadoEmergencia = digitalRead(PIN_EMERGENCIA_NF);
  estadoEmergenciaEstavel = ultimoEstadoEmergencia;
  emergenciaAtiva = estadoEmergenciaEstavel == HIGH;

  pinMode(PIN_RELE_AUTORIZACAO, OUTPUT);
  pinMode(PIN_RELE_COMANDO, OUTPUT);
  pinMode(PIN_LED_STATUS, OUTPUT);

  desligarSaidas();

  if (emergenciaAtiva) {
    Serial.println("EMERGENCIA ATIVA NA INICIALIZACAO. Saidas mantidas desligadas.");
    registrarLogSimples("EMERGENCIA_ATIVA_INICIALIZACAO", "BLOQUEADO", "GPIO33 em HIGH na partida");
  }

  limparBufferWiegand();

  attachInterrupt(digitalPinToInterrupt(PIN_WIEGAND_D0), isrD0, FALLING);
  attachInterrupt(digitalPinToInterrupt(PIN_WIEGAND_D1), isrD1, FALLING);

  carregarMestre();

  Serial.println("Sistema iniciado - VERSAO BOTAO TOGGLE COM LOG OFFLINE NTP + LITTLEFS.");
  Serial.println("GPIO23=D0, GPIO22=D1, GPIO32=Botao, GPIO33=Emergencia NF, GPIO18=Autorizacao, GPIO19=Comando, GPIO21=LED.");
  Serial.println("Teste inicial recomendado: deixar reles desconectados da potencia.");
  Serial.println("Comandos Serial: STATUS, RTC STATUS, RTC DIAG, HORA STATUS, RESET, MONITOR ON, MONITOR OFF. Para resetar, digite RESET e depois SIM.");
  Serial.println("Modo teste desativado: cartao mestre serve somente para administracao.");
  Serial.println("LED de status GPIO21 inibido para teste de ruido Wiegand.");
  Serial.println("Horario: DS3231 preserva a hora ao desligar; NTP acerta automaticamente o DS3231 quando houver internet.");
  Serial.println("Horario confiavel e salvo no LittleFS a cada 60s; sem RTC/NTP, hora recuperada e apenas ESTIMADA.");
  Serial.println("Logs sem hora confiavel ficam em arquivo separado ate NTP da MESMA inicializacao.");
  Serial.println("Teste do relogio no Monitor Serial: RTC STATUS ou RTC DIAG (diagnostico sem alteracoes).");

  xTaskCreatePinnedToCore(
    tarefaLogsOnline,
    "TarefaLogsOnline",
    8192,
    NULL,
    1,
    &tarefaLogsHandle,
    0
  );
}

// ===================== LOOP =====================
void loop() {
  atualizarSerial();

  uint64_t codigo = 0;

  if (obterCartao(codigo)) {
    if (modoAdmin) {
      tratarCartaoModoAdmin(codigo);
    } else {
      tratarCartaoNormal(codigo);
    }

    ultimoCartaoLido = codigo;
    horarioUltimoCartaoLido = millis();
  }

  atualizarEmergencia();
  atualizarBotao();
  atualizarTemporizadores();
  atualizarLedStatus();
  atualizarMonitorSerial();
}
