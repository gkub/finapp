# Finapp - Fresh Mac Setup

This is the shortest setup path for a new Apple Silicon Mac. Only this first
section must be performed manually; the included script handles the rest.

## Mandatory manual steps

### 1. Update macOS

Open **Apple menu -> System Settings -> General -> Software Update** and install
available updates.

### 2. Install Apple's command-line tools

Open the built-in **Terminal** app and run:

```bash
xcode-select --install
```

Accept the popup and wait for installation to finish.

### 3. Install Homebrew

Run the official installer:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Enable Homebrew on an Apple Silicon Mac:

```bash
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"
brew --version
```

### 4. Download Finapp

Apple's command-line tools include Git:

```bash
mkdir -p ~/Code
cd ~/Code
git clone https://github.com/gkub/finapp.git
cd finapp
```

## Automated Mac and terminal setup

For the recommended pastel-pink prompt:

```bash
./scripts/setup-mac.sh --cute
```

For Greg's general terminal behavior with Powerlevel10k:

```bash
./scripts/setup-mac.sh --classic
```

With no option, the script asks which appearance to use:

```bash
./scripts/setup-mac.sh
```

The script installs iTerm2, a Nerd Font, Git, GitHub CLI, Python, SQLite, Oh My
Zsh, Git integration, autosuggestions, syntax highlighting, useful shared history,
and the chosen prompt. It also walks her through her own GitHub authentication.

It does not copy Greg's account, SSH alias, email, credentials, Linux paths, or
developer toolchains. Existing shell files are backed up, and it is safe to rerun.

The cute option uses Starship's official **Pastel Powerline** preset, with rose,
coral, peach, and soft-blue prompt segments:

<https://starship.rs/presets/pastel-powerline>

Afterward, open **iTerm2 -> Settings -> Profiles -> Text -> Font** and select
**CaskaydiaCove Nerd Font** so all prompt icons display properly.

## Start Finapp

```bash
./run.sh
```

During first-run setup choose **Private GitHub sync**, accept her suggested
`HER_USERNAME/finapp_db`, and confirm it is private under her GitHub account. Her
database remains separate from Greg's database and the public source repository.

## Everyday use and updates

Until Finapp is packaged as a normal `.app`, launch it with:

```bash
cd ~/Code/finapp
./run.sh
```

To update:

```bash
cd ~/Code/finapp
git pull
./run.sh
```

Close Finapp normally so its private database can commit and push cleanly.
