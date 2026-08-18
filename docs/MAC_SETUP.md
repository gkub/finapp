# Finapp - Fresh Mac Setup

This guide is intended for a new Apple Silicon Mac, including M-series Pro models.
The terminal setup is only needed for installation and occasional updates; Finapp
can later be packaged as a normal macOS application with a Dock icon.

## 1. Update macOS

Open **Apple menu -> System Settings -> General -> Software Update** and install
the available updates.

## 2. Install Apple's command-line tools

Open the built-in **Terminal** application and run:

```bash
xcode-select --install
```

Accept the popup and wait for installation to finish.

## 3. Install Homebrew

Run the official Homebrew installer:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

On an Apple Silicon Mac, enable Homebrew in Zsh:

```bash
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"
brew --version
```

## 4. Install the required tools and terminal applications

```bash
brew install git gh python sqlite starship zsh-autosuggestions zsh-syntax-highlighting
brew install --cask iterm2 font-caskaydia-cove-nerd-font
```

Close Terminal and open **iTerm2** from Applications.

## 5. Connect her own GitHub account

In iTerm2, run:

```bash
gh auth login
```

Choose:

1. **GitHub.com**
2. **SSH**
3. Generate a new SSH key if prompted
4. Authenticate using the web browser

Verify the result:

```bash
gh auth status
ssh -T git@github.com
```

When SSH first asks whether to trust GitHub's host, answer `yes`. GitHub's
success message may also say it does not provide shell access; that is normal.

## 6. Install Oh My Zsh and the pastel prompt

Install Oh My Zsh:

```bash
sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"
```

Install Starship's official **Pastel Powerline** preset:

```bash
mkdir -p ~/.config
starship preset pastel-powerline -o ~/.config/starship.toml
echo 'eval "$(starship init zsh)"' >> ~/.zshrc
exec zsh
```

The preset uses rose, coral, peach, and soft blue segments. Its example and
screenshot are available at:

<https://starship.rs/presets/pastel-powerline>

For the icons to render properly, open:

**iTerm2 -> Settings -> Profiles -> Text -> Font**

Select **CaskaydiaCove Nerd Font**.

This configures the prompt, but not iTerm2's terminal background palette. A
matching blush/lavender iTerm2 colour preset can be added later without affecting
Finapp or GitHub.

## 7. Install Finapp

```bash
mkdir -p ~/Code
cd ~/Code
git clone https://github.com/gkub/finapp.git
cd finapp
./run.sh
```

During first-run setup:

1. Choose **Private GitHub sync**.
2. Accept the suggested `HER_USERNAME/finapp_db` repository.
3. Confirm that the repository is created as private under her GitHub account.

Her database is separate from the Finapp source repository and from Greg's
private database. Never give another person access to either user's `finapp_db`
repository.

## Everyday use and updates

For now, launch with:

```bash
cd ~/Code/finapp
./run.sh
```

To update Finapp later:

```bash
cd ~/Code/finapp
git pull
./run.sh
```

Close Finapp normally so its private database can commit and push cleanly.
