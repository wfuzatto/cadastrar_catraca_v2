# Cadastrar Catraca V2

Aplicativo **Windows 10/11 64 bits**, novo e independente da V1, para uso na rede local do HikCentral. Código criado do zero, sem copiar o projeto anterior.

## Download

Acesse **Releases** deste repositório e baixe `CadastrarCatracaV2.exe` na pré-release `v2.0.0-teste`. O GitHub Actions executa testes em Linux e monta o EXE num runner Windows. Credenciais **não** são incluídas no GitHub ou dentro do EXE.

## Telas independentes

- **Cadastro:** nome, sobrenome, remark (apartamento), grupo, cartão NFC via ACR122U, foto webcam com detecção e guia facial ou upload, datas de entrada e saída. Cria Visitor Reservation V2, opcionalmente check-in e aplica o access level da categoria. Em falha após criação, mostra IDs para impedir duplicações inadvertidas.
- **Editar Visitor Information:** pesquisar uma reserva, alterar nome, sobrenome, remark, grupo, foto ou NFC. Usa API `registerment/update`, preservando as datas consultadas.
- **Editar Visitor Reservation:** pesquisar uma reserva, alterar **só datas**; os horários são fornecidos pelas configurações. Usa API `appointment/update` V2, preservando dados retornados no VisitorInfo.
- **Configurações:** senha configurada pelo solicitante (validada contra um hash PBKDF2); servidor, porta, AppKey, AppSecret, SHA-256 do certificado, horários de entrada/saída (HH:MM:SS), formato UID, câmera, VALID TIMES (para QR) e níveis de acesso.

## Mapas de acesso

| Grupo | Access level |
|---|---|
| Day use | DAY_USE |
| Hóspedes Serra | VISITANTE_SERRA |
| Hóspedes Vale | VISITANTE_VALE |
| Visitors | LOJA ACQUAVALE |

O aplicativo consulta IDs dos access levels na API, antes de associar ao Visitor. Não cria níveis inexistentes. Se o cadastro já tiver sido criado e a associação falhar, o erro informa o identificador existente.

## Configuração local e credenciais

1. Na máquina Windows original, extraia `CadastrarCatracaV2.exe` e os dois arquivos recebidos **separadamente** (`settings.json` e `secrets.dpapi`) para a mesma pasta.
2. Inicie o EXE. Se o `secrets.dpapi` tiver sido protegido por outro usuário/máquina Windows, **não será possível descriptografá-lo**; nesse caso, informe AppKey e AppSecret em Configurações e salve para criar um novo segredo DPAPI.
3. O programa salva novas preferências em `%LOCALAPPDATA%\CadastrarCatracaV2`. A configuração do usuário local tem prioridade sobre o arquivo ao lado do EXE.
4. **Não suba** `settings.json`, `secrets.dpapi`, cartões NFC, dados pessoais, fotografias nem logs com credenciais ao GitHub.

O SHA-256 do certificado TLS informado é verificado **na mesma conexão** antes de transmitir dados. Se não corresponder, a operação é bloqueada.

## Teste por etapas

1. Abra Configurações e clique em **Testar HikCentral**.
2. Faça **Testar NFC** com a pulseira encostada no ACR122U. Confirme se o UID está no formato desejado.
3. Clique em **Testar webcam**; confirme o enquadramento automático e teste upload.
4. Somente após os testes, faça cadastro de um hóspede de teste.
5. Busque a reserva e valide a tela separada de Visitor Information.
6. Busque novamente e valide a tela separada de Visitor Reservation. Confira as datas no HikCentral.

## Limitações e pontos a validar na instalação real

- Este projeto não pode acessar `192.168.102.100` fora da rede local; portanto, a integração real, a compatibilidade da versão HikCentral, o equipamento NFC e a webcam devem ser validados no computador de destino.
- **VALID TIMES** da API `accessInfo.qrCodeValidNum` limita autenticação por QR Code segundo documentação HikCentral; não há comprovação de limite para pulseiras NFC por esse parâmetro.
- A API de edição de reserva exige `visitorInfoList` junto às datas. A V2 reutiliza o objeto retornado pelo servidor, mas é importante confirmar na versão local do HikCentral se alterações de datas preservam cartões e fotos; **não usar em registros reais antes desse teste**.
- Data de entrada/saída é informada no formato `DD/MM/AAAA`, convertida automaticamente para ISO 8601 com offset local.
- API/serviço HikCentral pode exigir que o módulo Visitor esteja licenciado e que aprovação automática esteja habilitada.
- A primeira execução do pacote PyInstaller pode demorar mais por extração de arquivos para pasta temporária.

## Desenvolvimento

Requer Python 3.12:

    python -m pip install -r requirements.txt
    python -m unittest discover -s tests -v
    python app.py

Build local Windows:

    pyinstaller --noconfirm --clean --onefile --windowed --name CadastrarCatracaV2 --collect-data cv2 --hidden-import PIL._tkinter_finder app.py

## Referências técnicas

- HikCentral OpenAPI Visitor APIs: https://enpinfo.hikvision.com/hkwsen/unzip/20260723200832_95640_doc/index.html
- [Guia OpenAPI da Hikvision v2.6.1](https://www.scribd.com/document/808988682/HikCentral-Professional-OpenAPI-V2-6-1-Developer-Guide-V2-6-1-20240806)
