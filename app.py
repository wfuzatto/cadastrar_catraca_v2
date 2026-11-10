"""Interface gráfica Windows - telas isoladas, projeto Cadastrar Catraca V2."""
from __future__ import annotations
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from datetime import datetime
from io import BytesIO
from PIL import Image, ImageTk, ImageOps
from core import (GROUPS, load_settings, save_settings, load_credentials, save_credentials,
                  check_password, read_acr122u, validate_dates, date_iso, create_payload,
                  update_information_payload, update_reservation_payload, HikCentral)

BG="#F3F6FA"; CARD="#FFFFFF"; NAV="#172B4D"; ACCENT="#087A9B"; TEXT="#17324D"; MUTED="#62748A"
FONT=("Segoe UI",11)
def styled_button(parent,text,command,primary=False):
    return tk.Button(parent,text=text,command=command,font=("Segoe UI",10,"bold"),
                     bg=ACCENT if primary else "#E7EFF5",fg="white" if primary else TEXT,
                     activebackground="#08617C" if primary else "#D4E2EC",
                     relief="flat",padx=18,pady=11,cursor="hand2")

class WebcamDialog(tk.Toplevel):
    """Visualização ao vivo, guia facial e autocaptura após estabilização."""
    def __init__(self, master, camera_index, on_capture):
        super().__init__(master)
        self.title("Webcam • enquadramento facial")
        self.geometry("740x660")
        self.configure(bg=BG)
        self.on_capture=on_capture; self.running=False; self.camera=None
        self.stable_since=None; self.closed=False
        self.preview=tk.Label(self,bg="#18263A")
        self.preview.pack(padx=18,pady=16)
        self.indicator=tk.Label(self,text="Centralize o rosto dentro da guia verde",font=FONT,bg=BG,fg=TEXT)
        self.indicator.pack(pady=6)
        controls=tk.Frame(self,bg=BG);controls.pack(pady=8)
        styled_button(controls,"Capturar agora",self.manual,True).pack(side="left",padx=8)
        styled_button(controls,"Cancelar",self.quit).pack(side="left",padx=8)
        self.protocol("WM_DELETE_WINDOW",self.quit)
        try:
            import cv2
            self.cv2=cv2
            self.camera=cv2.VideoCapture(int(camera_index), cv2.CAP_DSHOW)
            if not self.camera.isOpened():
                self.camera.release(); self.camera=cv2.VideoCapture(int(camera_index))
            if not self.camera.isOpened():
                raise RuntimeError(f"Não foi possível abrir a webcam {camera_index}.")
            detector=cv2.CascadeClassifier(cv2.data.haarcascades+"haarcascade_frontalface_default.xml")
            if detector.empty():
                raise RuntimeError("Detector facial OpenCV não encontrado.")
            self.detector=detector
            self.running=True
            self.after(100,self.update_frame)
        except Exception as exc:
            messagebox.showerror("Webcam",str(exc),parent=self)
            self.after(50,self.quit)

    def update_frame(self):
        if not self.running: return
        cv2=self.cv2
        ok,frame=self.camera.read()
        if not ok:
            self.indicator.configure(text="Sem imagem da webcam. Confira o dispositivo.",fg="#A32929")
            self.after(150,self.update_frame);return
        h,w=frame.shape[:2]
        gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
        faces=self.detector.detectMultiScale(gray,scaleFactor=1.15,minNeighbors=5,minSize=(95,95))
        best=max(faces,key=lambda f:f[2]*f[3]) if len(faces) else None
        centered=False
        if best is not None:
            x,y,fw,fh=map(int,best)
            centered = (abs((x+fw/2)-w/2)<w*0.18 and abs((y+fh/2)-h/2)<h*.22
                        and fw>=w*.18 and fh>=h*.2)
            cv2.rectangle(frame,(x,y),(x+fw,y+fh),(0,200,0) if centered else (0,170,255),3)
        cv2.ellipse(frame,(w//2,h//2),(int(w*.19),int(h*.36)),0,0,360,(40,200,80),2)
        if centered:
            if self.stable_since is None:self.stable_since=time.monotonic()
            elapsed=time.monotonic()-self.stable_since
            self.indicator.configure(text=f"Rosto detectado. Mantenha por {max(0,1-elapsed):.1f}s",fg="#147C4A")
            if elapsed>=1:
                self.last_frame=frame.copy(); self.capture();return
        else:
            self.stable_since=None
            self.indicator.configure(text="Alinhe um rosto no centro; ou capture manualmente",fg=TEXT)
        self.last_frame=frame.copy()
        scaled=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
        img=Image.fromarray(scaled);img.thumbnail((680,490))
        self.photo=ImageTk.PhotoImage(img)
        self.preview.configure(image=self.photo,width=img.width,height=img.height)
        self.after(45,self.update_frame)

    def manual(self):
        if getattr(self,"last_frame",None) is None:
            messagebox.showwarning("Webcam","Aguardando imagem.",parent=self);return
        self.capture()

    def capture(self):
        # A foto enviada não contém retângulos do guia visual.
        ok, raw = self.camera.read()
        if not ok: raw=self.last_frame
        img=Image.fromarray(self.cv2.cvtColor(raw,self.cv2.COLOR_BGR2RGB))
        self.quit()
        self.on_capture(img)

    def quit(self):
        self.running=False
        if self.camera is not None:self.camera.release()
        if not self.closed:
            self.closed=True;self.destroy()

class BasePage(tk.Frame):
    def __init__(self,master,app,title,subtitle):
        super().__init__(master,bg=BG)
        self.app=app
        tk.Label(self,text=title,font=("Segoe UI",22,"bold"),fg=TEXT,bg=BG).pack(anchor="w",padx=30,pady=(25,4))
        tk.Label(self,text=subtitle,font=("Segoe UI",10),fg=MUTED,bg=BG).pack(anchor="w",padx=30,pady=(0,15))
        self.body=tk.Frame(self,bg=CARD,highlightthickness=1,highlightbackground="#DFE5EB")
        self.body.pack(fill="both",expand=True,padx=30,pady=(0,24))
        self.content=tk.Frame(self.body,bg=CARD);self.content.pack(fill="both",expand=True,padx=24,pady=24)
        self.status=tk.StringVar(value="Pronto")
        tk.Label(self.body,textvariable=self.status,bg="#EAF2F7",fg=TEXT,anchor="w",wraplength=800,
                 font=("Segoe UI",10),padx=18,pady=12).pack(fill="x",side="bottom")

    def field(self,parent,label,default="",width=42):
        tk.Label(parent,text=label,bg=CARD,fg=MUTED,font=("Segoe UI",10,"bold")).pack(anchor="w",pady=(10,2))
        var=tk.StringVar(value=str(default))
        entry=ttk.Entry(parent,textvariable=var,width=width,font=FONT)
        if label=="AppSecret": entry.configure(show="*")
        entry.pack(fill="x",ipady=5)
        return var

    def group(self,parent,label,default="Hóspedes Vale"):
        tk.Label(parent,text=label,bg=CARD,fg=MUTED,font=("Segoe UI",10,"bold")).pack(anchor="w",pady=(10,2))
        var=tk.StringVar(value=default if default in GROUPS else "Hóspedes Vale")
        ttk.Combobox(parent,textvariable=var,values=list(GROUPS),state="readonly",font=FONT).pack(fill="x",ipady=4)
        return var

    def run(self,title,fn,success=None):
        if getattr(self.app,"busy",False):
            messagebox.showwarning("Operação em andamento","Conclua a operação atual antes de iniciar outra.",parent=self.app.root)
            return
        self.app.busy=True
        self.status.set(title+"...")
        self.app.root.update_idletasks()
        def worker():
            try:
                result=fn()
                def done():
                    self.app.busy=False
                    self.status.set(title+" concluído.")
                    if success:success(result)
                self.app.root.after(0,done)
            except Exception as exc:
                message=str(exc)
                def failed():
                    self.app.busy=False
                    self.status.set("Erro: "+message)
                    messagebox.showerror(title,message,parent=self.app.root)
                self.app.root.after(0,failed)
        threading.Thread(target=worker,daemon=True).start()

class PhotoFields:
    def photo_section(self,parent):
        area=tk.Frame(parent,bg=CARD);area.pack(fill="x",pady=12)
        self.photo_info=tk.StringVar(value="Nenhuma foto selecionada")
        self.photo_bytes=None
        styled_button(area,"Abrir webcam",self.open_webcam).pack(side="left",padx=(0,10))
        styled_button(area,"Carregar foto",self.load_image).pack(side="left",padx=(0,10))
        tk.Label(area,textvariable=self.photo_info,bg=CARD,fg=MUTED).pack(side="left")
        self.thumbnail=tk.Label(parent,bg=CARD);self.thumbnail.pack(anchor="w")

    def open_webcam(self):
        WebcamDialog(self.app.root,self.app.config.get("camera_index",0),self.accept_image)

    def load_image(self):
        name=filedialog.askopenfilename(parent=self.app.root,filetypes=[("Imagens","*.jpg *.jpeg *.png *.bmp")])
        if name:
            try:
                with Image.open(name) as img:self.accept_image(ImageOps.exif_transpose(img).copy())
            except Exception as exc:messagebox.showerror("Foto",str(exc),parent=self.app.root)

    def accept_image(self,img):
        if img.width<160 or img.height<160:
            messagebox.showerror("Foto","Imagem muito pequena (mínimo 160×160).",parent=self.app.root)
            return
        img=img.convert("RGB");img.thumbnail((960,960))
        output=BytesIO();img.save(output,format="JPEG",quality=88)
        self.photo_bytes=output.getvalue()
        img.thumbnail((120,120))
        self.tk_thumbnail=ImageTk.PhotoImage(img)
        self.thumbnail.configure(image=self.tk_thumbnail)
        self.photo_info.set(f"Foto selecionada ({len(self.photo_bytes)//1024} KB)")

class GuestPage(BasePage,PhotoFields):
    def __init__(self,parent,app):
        super().__init__(parent,app,"Cadastrar hóspede","Visitor Information + Visitor Reservation em uma operação nova.")
        form=tk.Frame(self.content,bg=CARD);form.pack(anchor="nw",fill="both",expand=True)
        cols=tk.Frame(form,bg=CARD);cols.pack(fill="x")
        left=tk.Frame(cols,bg=CARD);left.pack(side="left",fill="x",expand=True,padx=(0,20))
        right=tk.Frame(cols,bg=CARD);right.pack(side="left",fill="x",expand=True)
        self.first=self.field(left,"Nome");self.last=self.field(left,"Sobrenome")
        self.apt=self.field(left,"Remark (apartamento)")
        self.group_var=self.group(left,"Grupo",app.config.get("preferred_group","Hóspedes Vale"))
        self.nfc=self.field(right,"Pulseira NFC (UID)")
        styled_button(right,"Ler ACR122U",self.read_nfc).pack(anchor="w",pady=(8,0))
        today=datetime.today().strftime("%d/%m/%Y")
        self.entry=self.field(right,"Data de entrada (DD/MM/AAAA)",today)
        self.exit=self.field(right,"Data de saída (DD/MM/AAAA)",today)
        self.photo_section(form)
        styled_button(form,"Cadastrar hóspede no HikCentral",self.submit,True).pack(anchor="w",pady=12)

    def read_nfc(self):
        self.run("Leitura NFC",lambda:read_acr122u(self.app.config["card_format"]),lambda value:self.nfc.set(value))

    def submit(self):
        def job():
            if not self.photo_bytes:raise ValueError("Selecione ou capture uma foto.")
            if not self.nfc.get().strip():raise ValueError("Leia a pulseira NFC.")
            payload=create_payload(self.app.config,self.first.get(),self.last.get(),self.apt.get(),
                                   self.group_var.get(),self.nfc.get(),self.photo_bytes,
                                   self.entry.get(),self.exit.get())
            return self.app.client().create(payload,self.group_var.get())
        def on_success(result):
            if isinstance(result,dict):
                self.status.set("Criado: "+", ".join(f"{k}={result.get(k)}" for k in ("visitorId","appointRecordId","appointCode")))
                messagebox.showinfo("Cadastro",self.status.get(),parent=self.app.root)
        self.run("Cadastro do hóspede",job,on_success)

class RecordPage(BasePage):
    def search_bar(self):
        wrapper=tk.Frame(self.content,bg=CARD);wrapper.pack(fill="x")
        self.searchid=self.field(wrapper,"Número da reserva (código ou ID)")
        styled_button(wrapper,"Buscar no HikCentral",self.lookup).pack(anchor="w",pady=8)
        self.record=None
        self.searched=tk.StringVar(value="Nenhum registro carregado")
        tk.Label(wrapper,textvariable=self.searched,fg=ACCENT,bg=CARD,font=("Segoe UI",10,"bold")).pack(anchor="w",pady=4)

    def lookup(self):
        key=self.searchid.get().strip()
        if not key:
            messagebox.showwarning("Busca","Informe o código ou ID da reserva.",parent=self.app.root);return
        self.record=None
        self.run("Consulta da reserva",lambda:self.app.client().search_reservation(key),self.populate)

class VisitorPage(RecordPage,PhotoFields):
    def __init__(self,parent,app):
        super().__init__(parent,app,"Editar Visitor Information","Altera somente dados pessoais, fotografia e pulseira.")
        self.search_bar()
        row=tk.Frame(self.content,bg=CARD);row.pack(fill="x")
        col1=tk.Frame(row,bg=CARD);col1.pack(side="left",fill="x",expand=True,padx=(0,18))
        col2=tk.Frame(row,bg=CARD);col2.pack(side="left",fill="x",expand=True)
        self.first=self.field(col1,"Nome");self.last=self.field(col1,"Sobrenome")
        self.apt=self.field(col1,"Remark (apartamento)");self.group_var=self.group(col1,"Grupo")
        self.nfc=self.field(col2,"Pulseira NFC")
        styled_button(col2,"Ler ACR122U",self.read_nfc).pack(anchor="w",pady=10)
        self.photo_section(self.content)
        styled_button(self.content,"Salvar Visitor Information",self.submit,True).pack(anchor="w",pady=6)

    def populate(self,record):
        self.record=record
        v=record.get("visitorInfo") or {}
        self.first.set(v.get("visitorGivenName",""))
        self.last.set(v.get("visitorFamilyName",""))
        self.apt.set(v.get("remark",""))
        self.group_var.set(v.get("visitorGroupName","Hóspedes Vale"))
        cards=v.get("cards") or []
        self.nfc.set(str(cards[0].get("cardNo","")) if cards and isinstance(cards[0],dict) else "")
        self.searched.set(f"Reserva {record.get('appointID','')} • visitante {v.get('visitorId','')}")

    def read_nfc(self):
        self.run("Leitura NFC",lambda:read_acr122u(self.app.config["card_format"]),self.nfc.set)

    def submit(self):
        if self.record is None:
            messagebox.showwarning("Edição","Busque uma reserva primeiro.",parent=self.app.root);return
        try:
            payload=update_information_payload(self.record,self.app.config,self.first.get(),self.last.get(),
                self.apt.get(),self.group_var.get(),self.nfc.get(),self.photo_bytes)
        except Exception as exc:
            messagebox.showerror("Visitor Information",str(exc),parent=self.app.root)
            return
        self.run("Salvar Visitor Information",lambda:self.app.client().edit_information(payload),lambda _:self.searched.set("Visitor Information salvo; atualize a busca."))

class ReservationPage(RecordPage):
    def __init__(self,parent,app):
        super().__init__(parent,app,"Editar Visitor Reservation","Altera exclusivamente as datas de entrada e saída.")
        self.search_bar()
        self.entry=self.field(self.content,"Data de entrada (DD/MM/AAAA)")
        self.exit=self.field(self.content,"Data de saída (DD/MM/AAAA)")
        tk.Label(self.content,text="Os horários HH:MM:SS vêm das Configurações. Os dados do visitante não são editáveis nesta tela.",
                 bg=CARD,fg=MUTED,wraplength=740,justify="left").pack(anchor="w",pady=20)
        styled_button(self.content,"Salvar Visitor Reservation",self.submit,True).pack(anchor="w",pady=8)

    def populate(self,record):
        self.record=record
        for name,var in (("appointStartTime",self.entry),("appointEndTime",self.exit)):
            value=record.get(name,"")
            try:var.set(datetime.fromisoformat(value).strftime("%d/%m/%Y"))
            except ValueError:var.set("")
        self.searched.set(f"Reserva {record.get('appointID','')} carregada")

    def submit(self):
        if self.record is None:
            messagebox.showwarning("Edição","Busque a reserva primeiro.",parent=self.app.root);return
        try:
            payload=update_reservation_payload(self.record,self.app.config,self.entry.get(),self.exit.get())
        except Exception as exc:
            messagebox.showerror("Visitor Reservation",str(exc),parent=self.app.root)
            return
        self.run("Salvar Visitor Reservation",lambda:self.app.client().edit_reservation(payload),
                 lambda _:self.searched.set("Datas salvas; refaça a busca."))

class SettingsPage(BasePage):
    def __init__(self,parent,app):
        super().__init__(parent,app,"Configurações","Área protegida • servidor, segurança, horários, dispositivos e grupos.")
        canvas=tk.Canvas(self.content,highlightthickness=0,bg=CARD)
        scrollbar=ttk.Scrollbar(self.content,orient="vertical",command=canvas.yview)
        frame=tk.Frame(canvas,bg=CARD)
        frame.bind("<Configure>",lambda e:canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0,0),window=frame,anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left",fill="both",expand=True);scrollbar.pack(side="right",fill="y")
        self.inputs={}
        keys=[("host","Servidor"),("port","Porta"),
              ("entry_time","Horário de entrada (HH:MM:SS)"),
              ("exit_time","Horário de saída (HH:MM:SS)"),
              ("cert_pin_sha256","SHA-256 do certificado TLS"),
              ("ca_file","Caminho do certificado CA (opcional)"),
              ("camera_index","Índice da webcam"),
              ("valid_times","VALID TIMES - QR Code (0 = sem limite)")]
        for key,label in keys:self.inputs[key]=self.field(frame,label,app.config.get(key,""))
        self.inputs["card_format"]=self.group_or_format(frame)
        self.inputs["app_key"]=self.field(frame,"AppKey",app.key)
        self.inputs["app_secret"]=self.field(frame,"AppSecret",app.secret)
        self.acl={}
        tk.Label(frame,text="Níveis de acesso por grupo",font=("Segoe UI",12,"bold"),fg=TEXT,bg=CARD).pack(anchor="w",pady=(20,3))
        for group,default in GROUPS.items():
            actual=(app.config.get("group_access",{}).get(group) or [default])[0]
            self.acl[group]=self.field(frame,group,actual)
        buttons=tk.Frame(frame,bg=CARD);buttons.pack(fill="x",pady=20)
        styled_button(buttons,"Salvar configurações",self.save,True).pack(side="left",padx=(0,8))
        styled_button(buttons,"Testar HikCentral",self.test_server).pack(side="left",padx=(0,8))
        styled_button(buttons,"Testar NFC",self.test_nfc).pack(side="left",padx=(0,8))
        styled_button(buttons,"Testar webcam",self.test_camera).pack(side="left")

    def group_or_format(self,parent):
        tk.Label(parent,text="FORMATO UID NFC",bg=CARD,fg=MUTED,font=("Segoe UI",10,"bold")).pack(anchor="w",pady=(10,2))
        var=tk.StringVar(value=self.app.config.get("card_format","DECIMAL_LITTLE"))
        ttk.Combobox(parent,textvariable=var,state="readonly",
                     values=["DECIMAL_LITTLE","DECIMAL_BIG","HEX_LITTLE","HEX_BIG"],font=FONT).pack(fill="x",ipady=4)
        return var

    def save(self):
        try:
            cfg=dict(self.app.config)
            for k,v in self.inputs.items():
                if k not in ("app_key","app_secret"):cfg[k]=v.get().strip()
            cfg["port"]=int(cfg["port"])
            cfg["camera_index"]=int(cfg["camera_index"])
            cfg["valid_times"]=int(cfg["valid_times"])
            if cfg["valid_times"]<0:raise ValueError("VALID TIMES deve ser maior ou igual a zero.")
            if not (1<=cfg["port"]<=65535):raise ValueError("Porta inválida.")
            from core import to_local_iso
            today=datetime.today().strftime("%d/%m/%Y")
            to_local_iso(today,cfg["entry_time"]);to_local_iso(today,cfg["exit_time"])
            cfg["group_access"]={k:[v.get().strip()] for k,v in self.acl.items()}
            if any(not a[0] for a in cfg["group_access"].values()):
                raise ValueError("Preencha todos os níveis de acesso.")
            save_settings(cfg)
            save_credentials(self.inputs["app_key"].get().strip(),self.inputs["app_secret"].get().strip())
            self.app.config,self.app.key,self.app.secret=cfg,self.inputs["app_key"].get().strip(),self.inputs["app_secret"].get().strip()
            self.status.set("Configurações salvas em %LOCALAPPDATA%/CadastrarCatracaV2.")
        except Exception as exc:messagebox.showerror("Configurações",str(exc),parent=self.app.root)

    def test_server(self):
        self.run("Teste da API",lambda:self.app.client().version(),lambda result:messagebox.showinfo("HikCentral",str(result)[:1000],parent=self.app.root))

    def test_nfc(self):
        self.run("Teste do ACR122U",lambda:read_acr122u(self.app.config["card_format"]),
                 lambda value:messagebox.showinfo("ACR122U","UID: "+value,parent=self.app.root))

    def test_camera(self):
        WebcamDialog(self.app.root,self.app.config.get("camera_index",0),lambda image:self.status.set(f"Webcam OK ({image.width} × {image.height})."))

class App:
    def __init__(self):
        self.root=tk.Tk();self.root.title("Cadastrar Catraca V2")
        self.root.geometry("1170x800");self.root.minsize(1020,680);self.root.configure(bg=BG)
        try:self.config=load_settings()
        except Exception as exc:
            self.config={**__import__("core").DEFAULT}
            messagebox.showerror("Configuração","settings.json inválido: "+str(exc))
        try:self.key,self.secret=load_credentials()
        except Exception as exc:
            self.key,self.secret="",""
            messagebox.showwarning("Credenciais","Não foi possível abrir secrets.dpapi nesta conta Windows: "+str(exc))
        self.unlocked=False
        self.busy=False
        self.nav=tk.Frame(self.root,bg=NAV,width=240);self.nav.pack(side="left",fill="y");self.nav.pack_propagate(False)
        tk.Label(self.nav,text="CATRACA\nV2",font=("Segoe UI",23,"bold"),fg="#FFFFFF",bg=NAV,justify="left").pack(anchor="w",padx=25,pady=(28,34))
        self.view=tk.Frame(self.root,bg=BG);self.view.pack(fill="both",expand=True)
        self.pages={
            "Cadastro":GuestPage(self.view,self),
            "Visitor Information":VisitorPage(self.view,self),
            "Visitor Reservation":ReservationPage(self.view,self),
            "Configurações":SettingsPage(self.view,self),
        }
        for name,page in self.pages.items():
            tk.Button(self.nav,text=name,font=("Segoe UI",11),anchor="w",fg="white",bg=NAV,
                      activebackground="#274C74",activeforeground="white",relief="flat",
                      padx=25,pady=16,command=lambda n=name:self.show(n)).pack(fill="x",pady=1)
        tk.Label(self.nav,text="Build 2.0 • Rede local",fg="#98B1C8",bg=NAV,font=("Segoe UI",9)).pack(side="bottom",pady=26)
        self.current=None;self.show("Cadastro")

    def client(self):
        return HikCentral(self.config,self.key,self.secret)

    def show(self,name):
        if name=="Configurações" and not self.unlocked:
            entry=simpledialog.askstring("Configurações","Senha de acesso:",show="*",parent=self.root)
            if entry is None or not check_password(entry):
                if entry is not None:messagebox.showerror("Acesso negado","Senha incorreta.",parent=self.root)
                return
            self.unlocked=True
        if self.current:self.current.pack_forget()
        self.current=self.pages[name]
        self.current.pack(fill="both",expand=True)

if __name__=="__main__":
    App().root.mainloop()
