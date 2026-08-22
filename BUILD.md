# Como gerar os instaladores do Port Killer

O script `build.py` automatiza todo o processo. Ele instala as dependências,
empacota o Python + psutil no executável com PyInstaller e gera o instalador
nativo da plataforma.

---

## Pré-requisitos comuns (todas as plataformas)

```
Python 3.10+   (já instala tkinter junto)
pip install pyinstaller psutil
```

PyInstaller embute o Python e o psutil no executável final — o usuário
**não** precisa ter Python instalado.

---

## Windows

### Ferramentas necessárias
| Ferramenta | Obrigatório | Onde baixar |
|---|---|---|
| Python 3.x (com tkinter) | Sim | python.org |
| PyInstaller | Sim | `pip install pyinstaller` |
| Inno Setup 6.3+ | Para o `.exe` instalador | jrsoftware.org/isdl.php |

### Build
```cmd
python build.py
```

Resultado: `installer\windows\Output\PortKiller_Setup_1.0.0.exe`

Sem o Inno Setup, o script entrega apenas o `dist\PortKiller.exe` standalone.

---

## Linux

### Ferramentas necessárias
| Ferramenta | Obrigatório | Onde obter |
|---|---|---|
| Python 3.x (com tkinter) | Sim | `sudo apt install python3 python3-tk` |
| PyInstaller | Sim | `pip install pyinstaller` |
| appimagetool | Para o `.AppImage` | github.com/AppImage/AppImageKit/releases |

```bash
# Baixar appimagetool e colocar no PATH
chmod +x appimagetool-x86_64.AppImage
sudo mv appimagetool-x86_64.AppImage /usr/local/bin/appimagetool
```

### Build
```bash
python3 build.py
```

Resultado: `dist/PortKiller-1.0.0-x86_64.AppImage`

Sem o appimagetool, o script entrega apenas o binário `dist/PortKiller` standalone.

---

## macOS

### Ferramentas necessárias
| Ferramenta | Obrigatório | Onde obter |
|---|---|---|
| Python 3.x (com tkinter) | Sim | python.org ou `brew install python-tk` |
| PyInstaller | Sim | `pip install pyinstaller` |
| hdiutil | Para o `.dmg` | **Já vem no macOS** — nenhuma instalação |
| create-dmg (opcional) | DMG mais bonito | `brew install create-dmg` |

### Build
```bash
python3 build.py
```

Resultado: `dist/PortKiller-1.0.0.dmg`

---

## Estrutura dos arquivos de build

```
port-killer/
├── port_killer.py              # Aplicação principal (define APP_VERSION)
├── requirements.txt            # psutil>=5.9.0
├── port_killer.spec            # Configuração do PyInstaller
├── build.py                    # Script de build unificado
├── tests/
│   └── test_port_killer.py     # Suíte de testes (stdlib unittest)
└── installer/
    ├── windows/
    │   ├── setup.iss           # Script do Inno Setup
    │   ├── port_killer.ico     # Ícone do .exe e do instalador
    │   └── Output/             # Gerado: instalador .exe
    ├── linux/
    │   ├── AppRun              # Entry point do AppImage
    │   ├── port_killer.desktop # Integração com desktop Linux
    │   ├── port_killer.png     # Ícone exigido pelo appimagetool
    │   └── AppDir/             # Gerado durante o build
    └── macos/
        ├── build_dmg.sh        # Script auxiliar para o DMG
        └── port_killer.icns    # Ícone do .app
```

## Versão

`APP_VERSION` em `port_killer.py` é a fonte única. O `build.py`, o
`port_killer.spec`, o `setup.iss` (via `/DAppVersion`) e o `build_dmg.sh` leem
de lá — para lançar uma versão nova, basta alterar essa linha.

## Testes

```bash
python -m unittest discover -s tests -v
```

---

## Nota sobre builds cruzados

PyInstaller **não** suporta cross-compilation — cada plataforma deve ser
compilada em sua própria máquina (ou via CI/CD como GitHub Actions).
