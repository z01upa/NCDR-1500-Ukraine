# Lenovo Windows 11: GitHub, Python та локальний Qwen

Ці команди призначені для публічного репозиторію `z01upa/NCDR-1500-Ukraine`. Потрібен доступ GitHub до цього репозиторію. Git LFS зазвичай входить до Git for Windows. Якщо `git lfs version` не спрацьовує, встановіть Git LFS з [офіційної сторінки](https://git-lfs.com), відкрийте нове вікно PowerShell і повторіть перевірку.

## 1. Інструменти й автентифікація

Відкрийте PowerShell. Якщо Git або GitHub CLI відсутні:

```powershell
winget install --id Git.Git --exact --source winget
winget install --id GitHub.cli --exact --source winget
```

Закрийте й відкрийте PowerShell, тоді:

```powershell
git --version
git lfs version
gh --version
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git
gh auth status
```

У браузері завершіть авторизацію в акаунті GitHub із правом push у цей репозиторій. Для публічного clone авторизація не потрібна. Не вставляйте токени в командний рядок або файли.

## 2. Клонування

```powershell
$RepoPath = Join-Path $HOME 'NCDR-1500-Ukraine'
gh repo clone z01upa/NCDR-1500-Ukraine $RepoPath
Set-Location $RepoPath
git lfs install --local
git lfs pull
git status --short --branch
```

## 3. Локальне джерело даних

Оригінальні карти й firmware у GitHub не входять. Якщо вони правомірно доступні локально, вкажіть шлях до їхнього кореня в поточному PowerShell-сеансі (не комітьте локальну конфігурацію):

```powershell
$env:NCDR_SOURCE_ROOT = 'D:\NCDR-Original'
```

Скрипти читають з цього кореня та працюють з копіями/виходами у проєкті. Якщо змінну не задати, як корінь джерела використовується каталог репозиторію; бінарні входи там відсутні.

## 4. Python-залежності

Потрібен Python 3.10 або новіший. У корені репозиторію:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
python -m pip install -r requirements.txt
```

Основний пакет використовує стандартну бібліотеку Python; `requirements.txt` підключає `pypcode==2.0.0` для відповідних дослідницьких скриптів.

## 5. Ollama і Qwen Coder локально

Встановіть Ollama для Windows з офіційного сайту або в PowerShell:

```powershell
irm https://ollama.com/install.ps1 | iex
```

Після інсталяції в новому PowerShell:

```powershell
ollama pull qwen2.5-coder:7b
ollama run qwen2.5-coder:7b
```

`qwen2.5-coder:7b` відповідає наявній конфігурації проєкту; модель займає близько 4.7 GB на диску. Для слабшого Lenovo можна обрати `qwen2.5-coder:3b`. Потреба в оперативній/відеопам'яті залежить від контексту та апаратури. Не використовуйте тег із суфіксом `-cloud` для локальної роботи.

Ollama на Windows обслуговує локальний API на `http://127.0.0.1:11434`. Щоб перевірити наявність моделі:

```powershell
ollama list
```

## 6. Робота з кодом

Відкрийте цей каталог у редакторі, прочитайте `AGENTS.md` і спілкуйтеся з локальною моделлю через Ollama-клієнт вашого редактора. Не запускайте автономний NCDR worker чи нові дослідницькі задачі без окремого запиту; цей репозиторій зберігає дослідження й докази, але не дає дозволу змінювати Writer, MP0 або firmware.


## Офіційні джерела

- [Встановлення GitHub CLI на Windows](https://github.com/cli/cli/blob/trunk/docs/install_windows.md)
- [Встановлення Git LFS на Windows](https://docs.github.com/en/repositories/working-with-files/managing-large-files/installing-git-large-file-storage?platform=windows)
- [Встановлення Ollama на Windows](https://ollama.com/download/windows)
- [Модель qwen2.5-coder:7b в Ollama](https://ollama.com/library/qwen2.5-coder%3A7b)
