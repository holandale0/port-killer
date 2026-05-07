# 🔌 Port Killer

Utilitário desktop para **verificar e encerrar processos** que estão ocupando uma porta de rede — com interface gráfica moderna e suporte a **Windows**, **Linux** e **macOS**.

Desenvolvido com **Python 3** e **tkinter**, usando **psutil** para inspeção de processos e conexões em tempo real.

<p align="center">
  <a href="https://github.com/holandale0/port-killer/releases/download/v1.0.0/PortKiller_Setup_1.0.0.exe">
    <img src="https://img.shields.io/badge/Download-Windows-0078D4?style=for-the-badge&logo=windows&logoColor=white" alt="Download Windows"/>
  </a>
  &nbsp;
  <a href="https://github.com/holandale0/port-killer/releases/download/v1.0.0/PortKiller-1.0.0-x86_64.AppImage">
    <img src="https://img.shields.io/badge/Download-Linux-E95420?style=for-the-badge&logo=linux&logoColor=white" alt="Download Linux"/>
  </a>
  &nbsp;
  <a href="https://github.com/holandale0/port-killer/releases/download/v1.0.0/PortKiller-1.0.0.dmg">
    <img src="https://img.shields.io/badge/Download-macOS-000000?style=for-the-badge&logo=apple&logoColor=white" alt="Download macOS"/>
  </a>
</p>

---

## 📸 Screenshots

| Porta livre | Porta em uso |
|:-----------:|:------------:|
| ![Porta livre](captures/free.png) | ![Porta em uso](captures/in_use.png) |

---

## ✨ Funcionalidades

- Verifica qual processo está usando uma porta específica (1–65535)
- Exibe **PID**, **nome do processo** e **status da conexão** em tempo real
- Encerra o processo diretamente pela interface, com diálogo de confirmação
- Interface **dark mode** com tema [Catppuccin Mocha](https://github.com/catppuccin/catppuccin)
- Distribuído como executável standalone — **sem precisar instalar Python**

---

## 🧰 Tecnologias

| Tecnologia | Versão | Uso |
|---|---|---|
| Python | 3.10+ | Linguagem principal |
| tkinter | built-in | Interface gráfica |
| psutil | ≥ 5.9.0 | Inspeção de processos e conexões de rede |
| PyInstaller | ≥ 6.0 | Empacotamento do executável standalone |
| Inno Setup | 6 | Criação do instalador Windows (.exe) |

---

## 💻 Instalação

### Executável pré-compilado (recomendado)

Baixe o instalador do seu sistema na página de [Releases](https://github.com/holandale0/port-killer/releases):

| Plataforma | Arquivo |
|---|---|
| Windows 10 / 11 (64-bit) | `PortKiller_Setup_1.0.0.exe` |
| Linux (x86_64) | `PortKiller-1.0.0-x86_64.AppImage` |
| macOS | `PortKiller-1.0.0.dmg` |

> O instalador já inclui o Python e todas as dependências — nenhuma instalação prévia é necessária.

### Executar pelo código-fonte

```bash
git clone https://github.com/holandale0/port-killer.git
cd port-killer
pip install -r requirements.txt
python port_killer.py
```

---

## 🏗️ Gerar os instaladores

Execute o script de build na plataforma desejada. Ele instala o PyInstaller, empacota o executável com Python embutido e gera o instalador nativo automaticamente.

```bash
python build.py
```

Resultado por plataforma:

| Plataforma | Pré-requisito extra | Saída |
|---|---|---|
| Windows | [Inno Setup 6](https://jrsoftware.org/isdl.php) | `installer/windows/Output/PortKiller_Setup_1.0.0.exe` |
| Linux | [appimagetool](https://github.com/AppImage/AppImageKit/releases) | `dist/PortKiller-1.0.0-x86_64.AppImage` |
| macOS | `hdiutil` *(já incluso no macOS)* | `dist/PortKiller-1.0.0.dmg` |

> Cada plataforma deve ser compilada em sua própria máquina — PyInstaller não suporta cross-compilation.

---

## ✅ Checklist

- [x] Verificação de porta em tempo real
- [x] Exibição de PID, nome e status do processo
- [x] Encerramento de processo com confirmação
- [x] Interface dark mode (Catppuccin Mocha)
- [x] Instalador Windows com wizard (Inno Setup)
- [x] AppImage para Linux
- [x] DMG para macOS
- [x] Script de build automatizado (`build.py`)

---

## ⚠️ Permissões

Em alguns sistemas pode ser necessário executar como **Administrador** (Windows) ou com **sudo** (Linux/macOS) para visualizar processos de sistema ou encerrar processos privilegiados.
