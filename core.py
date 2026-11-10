"""Núcleo da V2. Sem dependência do aplicativo V1."""
from __future__ import annotations
import base64
import ctypes
import hashlib
import hmac
import http.client
import json
import os
import re
import ssl
import sys
import uuid
from ctypes import wintypes
from datetime import date, datetime, timedelta
from pathlib import Path

GROUPS = {
    "Day use": "DAY_USE",
    "Hóspedes Serra": "VISITANTE_SERRA",
    "Hóspedes Vale": "VISITANTE_VALE",
    "Visitors": "LOJA ACQUAVALE",
}
DEFAULT = {
    "host": "192.168.102.100", "port": 443,
    "cert_pin_sha256": "944D1E25B46E5BBFD4143F737260C200466A30093197BEE258AB9B5E17382A18",
    "ca_file": "", "entry_time": "09:00:00", "exit_time": "17:00:00",
    "card_format": "DECIMAL_LITTLE", "camera_index": 0, "valid_times": 0,
    "preferred_group": "Hóspedes Vale", "group_access": {k: [v] for k,v in GROUPS.items()},
}
DATA_DIR = Path(os.getenv("LOCALAPPDATA") or Path.home()) / "CadastrarCatracaV2"

def sibling_path(name):
    return Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent / name

def load_settings():
    config = dict(DEFAULT)
    p = DATA_DIR / "settings.json"
    if not p.exists() and sibling_path("settings.json").exists():
        p = sibling_path("settings.json")
    if p.exists():
        saved = json.loads(p.read_text(encoding="utf-8-sig"))
        config.update(saved)
    # Compatibilidade com o arquivo de configuração fornecido, sem importar código da V1.
    tickets = config.get("tickets", {})
    config.setdefault("entry_time", str(tickets.get("1 dia", {}).get("checkin", "09:00"))[:5] + ":00")
    config.setdefault("exit_time", str(tickets.get("1 dia", {}).get("checkout", "17:00"))[:5] + ":00")
    return config

def save_settings(config):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    values = {k:v for k,v in config.items() if k not in ("app_key", "app_secret")}
    (DATA_DIR / "settings.json").write_text(json.dumps(values, indent=2, ensure_ascii=False), encoding="utf-8")

class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

def _blob(value: bytes):
    buf = ctypes.create_string_buffer(value)
    return DATA_BLOB(len(value), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte))), buf

def dpapi(data, protect):
    if sys.platform != "win32":
        raise RuntimeError("A criptografia DPAPI requer Windows.")
    crypt = ctypes.windll.crypt32
    kernel = ctypes.windll.kernel32
    source, hold = _blob(data)
    dest = DATA_BLOB()
    func = crypt.CryptProtectData if protect else crypt.CryptUnprotectData
    if protect:
        ok = func(ctypes.byref(source), "Cadastrar Catraca V2", None, None, None, 0, ctypes.byref(dest))
    else:
        ok = func(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(dest))
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(dest.pbData, dest.cbData)
    finally:
        kernel.LocalFree(dest.pbData)

def load_credentials():
    p = DATA_DIR / "secrets.dpapi"
    if not p.exists():
        p = sibling_path("secrets.dpapi")
    if not p.exists():
        return "", ""
    raw = dpapi(p.read_bytes(), False)
    try:
        data = json.loads(raw.decode("utf-8-sig"))
        if isinstance(data, dict):
            return (str(data.get("app_key") or data.get("appKey") or data.get("AppKey") or ""),
                    str(data.get("app_secret") or data.get("appSecret") or data.get("AppSecret") or ""))
        if isinstance(data, list) and len(data) == 2:
            return str(data[0]), str(data[1])
    except (ValueError, UnicodeError):
        pass
    plain = raw.decode("utf-8-sig").strip()
    for sep in ("\r\n", "\n", "|", ";"):
        chunks = plain.split(sep)
        if len(chunks) == 2:
            return chunks[0].strip(), chunks[1].strip()
    raise ValueError("Formato de credenciais DPAPI desconhecido; informe AppKey e AppSecret nas Configurações.")

def save_credentials(key, secret):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw = json.dumps({"app_key":key, "app_secret":secret}).encode("utf-8")
    (DATA_DIR / "secrets.dpapi").write_bytes(dpapi(raw, True))

def check_password(value):
    digest = hashlib.pbkdf2_hmac("sha256", value.encode(), b"catraca-v2-config-2026", 250000)
    return hmac.compare_digest(digest.hex(), "e422249bb47ef4e2fca266364c00b30c0c032e8a73ba50afc76e2579e4719eb2")

def date_iso(value):
    return datetime.strptime(value.strip(), "%d/%m/%Y").date().isoformat()

def to_local_iso(day, time_hms):
    if not re.fullmatch(r"\d{2}:\d{2}:\d{2}", time_hms):
        raise ValueError("Horário deve ser HH:MM:SS.")
    d = datetime.fromisoformat(f"{date_iso(day)}T{time_hms}")
    offset = datetime.now().astimezone().utcoffset() or timedelta()
    sign = "+" if offset.total_seconds() >= 0 else "-"
    offset = abs(offset)
    return f"{d.isoformat()}{sign}{int(offset.total_seconds()//3600):02d}:{int(offset.total_seconds()%3600//60):02d}"

def validate_dates(entry, exit_):
    start, end = date.fromisoformat(date_iso(entry)), date.fromisoformat(date_iso(exit_))
    if end < start:
        raise ValueError("A data de saída não pode anteceder a entrada.")
    return start, end

def uid_format(uid, fmt):
    if not uid:
        raise ValueError("UID vazio.")
    buf = bytes(uid)
    if fmt == "DECIMAL_LITTLE":
        return str(int.from_bytes(buf, "little"))
    if fmt == "DECIMAL_BIG":
        return str(int.from_bytes(buf, "big"))
    if fmt == "HEX_LITTLE":
        return buf[::-1].hex().upper()
    if fmt == "HEX_BIG":
        return buf.hex().upper()
    raise ValueError("Formato UID NFC inválido.")

def read_acr122u(fmt="DECIMAL_LITTLE"):
    """PC/SC nativo de Windows, sem driver proprietário e sem dependência da V1."""
    if sys.platform != "win32":
        raise RuntimeError("Leitura ACR122U disponível somente no Windows.")
    lib = ctypes.WinDLL("winscard.dll")
    lib.SCardEstablishContext.argtypes = [wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    lib.SCardListReadersW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.POINTER(wintypes.DWORD)]
    lib.SCardConnectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD)]
    lib.SCardDisconnect.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ctx = ctypes.c_void_p()
    if lib.SCardEstablishContext(2, None, None, ctypes.byref(ctx)) != 0:
        raise RuntimeError("Não foi possível iniciar o serviço de cartão inteligente Windows.")
    try:
        length = wintypes.DWORD()
        if lib.SCardListReadersW(ctx, None, None, ctypes.byref(length)) != 0 or not length.value:
            raise RuntimeError("Nenhum leitor PC/SC encontrado.")
        readers = ctypes.create_unicode_buffer(length.value)
        if lib.SCardListReadersW(ctx, None, readers, ctypes.byref(length)) != 0:
            raise RuntimeError("Falha ao listar leitores PC/SC.")
        items = readers[:length.value].strip("\0").split("\0")
        reader = next((r for r in items if "ACR122" in r.upper()), None)
        if not reader:
            raise RuntimeError("ACR122U não detectado. Leitores encontrados: " + ", ".join(items))
        card = ctypes.c_void_p()
        proto = wintypes.DWORD()
        code = lib.SCardConnectW(ctx, reader, 2, 3, ctypes.byref(card), ctypes.byref(proto))
        if code != 0:
            raise RuntimeError(f"Aproxime a pulseira do ACR122U (PC/SC: 0x{code & 0xffffffff:08X}).")
        try:
            class IO(ctypes.Structure):
                _fields_ = [("dwProtocol", wintypes.DWORD), ("cbPciLength", wintypes.DWORD)]
            pci = IO(proto.value, ctypes.sizeof(IO))
            send = (ctypes.c_ubyte * 5)(0xFF, 0xCA, 0, 0, 0)
            recv = (ctypes.c_ubyte * 258)()
            recv_size = wintypes.DWORD(len(recv))
            lib.SCardTransmit.argtypes = [ctypes.c_void_p, ctypes.POINTER(IO), ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
            code = lib.SCardTransmit(card, ctypes.byref(pci), send, len(send), None, recv, ctypes.byref(recv_size))
            if code or recv_size.value < 3 or bytes(recv[recv_size.value-2:recv_size.value]) != b"\x90\x00":
                raise RuntimeError(f"Falha ao ler UID (PC/SC: 0x{code & 0xffffffff:08X}).")
            return uid_format(bytes(recv[:recv_size.value-2]), fmt)
        finally:
            lib.SCardDisconnect(card, 0)
    finally:
        lib.SCardReleaseContext(ctx)

def visitor_info(first, last, apt, group, nfc="", image=None, existing=None):
    if not first.strip() or not last.strip() or not apt.strip():
        raise ValueError("Preencha nome, sobrenome e apartamento.")
    if group not in GROUPS:
        raise ValueError("Grupo desconhecido.")
    v = dict(existing or {})
    v.update({"visitorGivenName":first.strip(), "visitorFamilyName":last.strip(),
              "remark":apt.strip(), "visitorGroupName":group})
    if nfc.strip():
        v["cards"] = [{"cardNo":nfc.strip()}]
    if image:
        v["faces"] = [{"faceData":base64.b64encode(image).decode("ascii")}]
    return v

def visitor_list(info):
    return [{"VisitorInfo": info}]

def create_payload(cfg, first, last, apt, group, nfc, image, entry, exit_):
    validate_dates(entry, exit_)
    info = visitor_info(first,last,apt,group,nfc,image)
    return {"appointStartTime":to_local_iso(entry,cfg["entry_time"]),
            "appointEndTime":to_local_iso(exit_,cfg["exit_time"]),
            "visitReasonType":0, "visitorInfoList":visitor_list(info)}

def update_information_payload(record, cfg, first, last, apt, group, nfc, image):
    """Somente dados de visitor; datas são preservadas do registro consultado."""
    visitor = record.get("visitorInfo") or {}
    info = visitor_info(first, last, apt, group, nfc, image, visitor)
    start, end = record.get("appointStartTime"), record.get("appointEndTime")
    if not start or not end:
        raise ValueError("O servidor não retornou datas; edição bloqueada para impedir alterações acidentais.")
    ident = record.get("appointID") or record.get("appointRecordId")
    if not ident:
        raise ValueError("ID da reserva ausente no servidor.")
    return {"appointRecordId":str(ident), "visitStartTime":start, "visitEndTime":end,
            "visitPurposeType":0, "visitorInfoList":visitor_list(info)}

def update_reservation_payload(record, cfg, entry, exit_):
    """Somente datas; todos os campos de VisitorInfo existentes são preservados."""
    validate_dates(entry,exit_)
    ident = record.get("appointID") or record.get("appointRecordId")
    original = record.get("visitorInfo") or {}
    if not ident or not original:
        raise ValueError("É necessário consultar a reserva e o VisitorInfo completo antes de editar as datas.")
    info = dict(original)
    # Dados de retorno que não pertencem ao corpo de atualização.
    for key in ("visitorId","visitorName","visitorPhoto","haveVisitorPhoto","haveIdentiPhoto"):
        info.pop(key,None)
    return {"appointRecordId":str(ident),
            "appointStartTime":to_local_iso(entry,cfg["entry_time"]),
            "appointEndTime":to_local_iso(exit_,cfg["exit_time"]),
            "visitReasonType":int(record.get("visitReasonType",0)),
            "visitReasonDetail":record.get("visitReasonDetail",""),
            "visitorInfoList":visitor_list(info)}

class HikCentral:
    def __init__(self, cfg, key, secret):
        self.cfg, self.key, self.secret = cfg, key, secret
        if not key or not secret:
            raise RuntimeError("AppKey/AppSecret indisponíveis; verifique secrets.dpapi na mesma conta Windows ou salve novas credenciais.")

    def post(self,path,payload):
        nonce = str(uuid.uuid4())
        stamp = str(int(datetime.now().timestamp()*1000))
        ctype = "application/json"
        accept = "application/json"
        headers_signed = {"x-ca-key":self.key, "x-ca-nonce":nonce, "x-ca-timestamp":stamp}
        names = sorted(headers_signed)
        canonical = ("POST\n" + accept + "\n" + "\n" + ctype + "\n" + "\n" +
                     "".join(f"{k}:{headers_signed[k]}\n" for k in names) + path)
        signature = base64.b64encode(hmac.new(self.secret.encode(),canonical.encode(),hashlib.sha256).digest()).decode()
        headers = {"Accept":accept, "Content-Type":ctype, "X-Ca-Key":self.key,
                   "X-Ca-Nonce":nonce, "X-Ca-Timestamp":stamp,
                   "X-Ca-Signature-Headers":",".join(names), "X-Ca-Signature":signature}
        host = self.cfg["host"].strip()
        port = int(self.cfg["port"])
        ca = self.cfg.get("ca_file") or None
        pin = re.sub(r"[^a-fA-F0-9]","",self.cfg.get("cert_pin_sha256","")).lower()
        if ca:
            ctx = ssl.create_default_context(cafile=ca)
        elif pin:
            ctx = ssl._create_unverified_context() # certificado verificado por fingerprint abaixo, na MESMA conexão
        else:
            raise RuntimeError("Configure certificado CA ou o SHA-256 do certificado; conexão insegura bloqueada.")
        conn = http.client.HTTPSConnection(host,port,context=ctx,timeout=15)
        try:
            conn.connect()
            if pin:
                current = hashlib.sha256(conn.sock.getpeercert(binary_form=True)).hexdigest().lower()
                if not hmac.compare_digest(pin,current):
                    raise RuntimeError("Certificado TLS não corresponde ao SHA-256 configurado.")
            body = json.dumps(payload,ensure_ascii=False,separators=(",",":")).encode("utf-8")
            conn.request("POST",path,body=body,headers=headers)
            resp = conn.getresponse()
            raw = resp.read(10*1024*1024)
            if resp.status >= 400:
                raise RuntimeError(f"HTTP {resp.status}: {raw[:500].decode('utf-8','replace')}")
            try:
                parsed = json.loads(raw)
            except ValueError:
                raise RuntimeError("Resposta não é JSON válido.")
            if str(parsed.get("code")) not in ("0","200"):
                raise RuntimeError(f"HikCentral: {parsed.get('code')} – {parsed.get('msg','sem detalhes')}")
            return parsed.get("data")
        finally:
            conn.close()

    def version(self):
        return self.post("/artemis/api/common/v1/version", {})

    def levels(self):
        names={}
        for group_type in (2,1):
            for page in range(1,6):
                data=self.post("/artemis/api/acs/v1/privilege/group",
                               {"pageNo":page,"pageSize":100,"type":group_type}) or {}
                rows=data.get("list",[]) if isinstance(data,dict) else []
                for item in rows:
                    name=item.get("privilegeGroupName")
                    if name: names[name]=str(item.get("privilegeGroupId"))
                if len(rows)<100: break
        return names

    def create(self,payload,group):
        data=self.post("/artemis/api/visitor/v2/appointment",payload) or {}
        # Aplicar os níveis somente APÓS o cadastro ser confirmado.
        visitor_id=str(data.get("visitorId",""))
        if visitor_id:
            self.apply_level(visitor_id,group)
        return data

    def apply_level(self, visitor_id, group):
        desired=self.cfg.get("group_access",{}).get(group,[GROUPS[group]])
        levels=self.levels()
        missing=[name for name in desired if name not in levels]
        if missing: raise RuntimeError("Reserva criada, mas nível de acesso não encontrado: "+", ".join(missing))
        for name in desired:
            self.post("/artemis/api/acs/v1/privilege/group/single/addPersons",
                      {"privilegeGroupId":levels[name],"type":2,"list":[{"id":visitor_id}]})

    def edit_information(self,payload):
        return self.post("/artemis/api/visitor/v1/registerment/update",payload)

    def edit_reservation(self,payload):
        return self.post("/artemis/api/visitor/v2/appointment/update",payload)

    def search_reservation(self,code_or_id):
        # Busca por código; se foi informado ID interno, compara localmente retornos recentes.
        now = datetime.now()
        start=(now-timedelta(days=366)).strftime("%d/%m/%Y")
        end=(now+timedelta(days=366)).strftime("%d/%m/%Y")
        for by_code in (True,False):
            for page in range(1,11):
                query={"pageNo":page,"pageSize":100,
                       "appointStartTime":to_local_iso(start,"00:00:00"),
                       "appointEndTime":to_local_iso(end,"23:59:59"),"appointState":-1}
                if by_code: query["appointCode"]=code_or_id
                data=self.post("/artemis/api/visitor/v1/appointment/appointmentlist",query) or {}
                rows=data.get("list",[]) if isinstance(data,dict) else []
                for rec in rows:
                    if str(rec.get("appointID") or rec.get("appointRecordId"))==str(code_or_id) or str(rec.get("appointCode"))==str(code_or_id):
                        return rec
                if len(rows)<100: break
        raise LookupError("Reserva não localizada nos últimos 12 meses e próximos 12 meses.")
