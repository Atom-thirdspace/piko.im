# Piko CLI

The terminal version of [Piko](https://piko.aryan.my). Pull a problem into a
folder, solve it in your own editor, run the samples locally, and send it to
the same judge the website uses — without opening a browser.

```
pip install piko-cli
piko login
piko get two-sum
cd two-sum && piko test
piko submit
```

## Features

**Solving**
- `piko get <slug>` scaffolds a folder with the statement, the sample cases,
  and a starter file for your language
- `piko test` runs the samples and shows the first failure with input,
  expected and got
- `piko run` / `piko diff` run your code on your own input and compare output
- `piko watch` re-runs the samples every time you save
- `piko submit` sends it to the real judge and waits for the verdict
- `piko case` adds your own test cases; `piko stress` generates random ones
  until your code disagrees with a brute force

**Finding work**
- `piko next` — the one thing to do right now
- `piko potd`, `piko problems`, `piko search`, `piko show`
- `piko tracks`, `piko track <slug>` — course paths, unit by unit
- `piko lesson <path>`, `piko editorial <slug>`, `piko hint <slug>`

**Progress**
- `piko streak`, `piko stats`, `piko mastery`, `piko badges`, `piko coins`
- `piko top` for the leaderboard, `piko inbox` for notifications,
  `piko profile <username>` for someone's public page

**Comfort**
- Python 3, C++17 and Java 17
- `piko ui` is a full-screen panel for browsing and testing in the terminal
- `piko init` + `piko sync` scaffold a whole track at once;
  `piko status` shows what's solved across it
- `--json` on any command prints the raw API response, so you can pipe it
- `piko completion bash|zsh|fish` for tab completion

## Setup

You need Python 3.9 or newer.

```
pip install piko-cli
```

Then sign in:

```
piko login              # opens a browser, saves the key it hands back
piko login --device     # prints a code to enter elsewhere, for headless boxes
piko login --token ...  # paste a key you made at /settings/#api
```

Check it worked with `piko whoami`. The key goes in `~/.piko/config.json`,
readable only by you. `piko logout` forgets it.

C++ and Java use whatever compiler is already on your `PATH` — `g++` for C++17,
`javac`/`java` for Java 17. Python needs nothing extra. Run `piko doctor` to see
what this machine can actually build; it names anything missing.

### Settings

| variable | effect |
| --- | --- |
| `PIKO_TOKEN` | API key to use, ahead of the saved one |
| `PIKO_API` | API base URL, ahead of the saved one |
| `PIKO_HOME` | where config and cache live (default `~/.piko`) |
| `EDITOR` / `VISUAL` | what `piko get --edit` opens |
| `NO_COLOR` | set to anything to turn off colour |

`piko config list` shows what is saved, `piko config set <key> <value>` changes
it, and `piko --api <url>` overrides the API base for one command.

## Using it instead of the website

The whole solve loop works here, and these are the pages it stands in for:

| on the site | in the terminal |
| --- | --- |
| problem page | `piko show <slug>`, or `piko get <slug>` to work on it |
| the built-in editor | your editor, on a real file |
| *Run* button | `piko test`, `piko run`, `piko watch` |
| *Submit* button and the verdict panel | `piko submit` |
| problems index | `piko problems`, `piko search` |
| a course path | `piko track <slug>`, `piko sync` |
| lessons and editorials | `piko lesson <path>`, `piko editorial <slug>` |
| dashboard and streak | `piko next`, `piko streak`, `piko stats` |
| mastery, badges, coins | `piko mastery`, `piko badges`, `piko coins` |
| leaderboard | `piko top` |
| notifications | `piko inbox` |
| someone's profile | `piko profile <username>` |

Two things are better here than on the site: your samples run on your own
machine, so the loop is instant and works offline once a problem is pulled; and
`piko submit --notify` plus `piko submit --commit` mean a submission ends in an
OS notification and a git commit without you watching a tab.

### What still needs a browser

The CLI covers solving and progress, not the whole product. Open the site for:

- signing up, and account settings including 2FA
- enrolling in a course path (`piko next` stays empty until you do)
- contests, the arena, and team play
- classroom and teacher features
- the community feed, blog and discussions
- cosmetics, billing, and anything you spend real money on

`piko open` opens the site in a browser when you need one.


## How to install Piko CLI using PyPI (COMING SOON!)
You can install piko cli by the pip command

pip install piko-cli

Using this command all the necessary packaged will be installed to run the Piko CLI

## Troubleshooting

- **Anything odd** — `piko doctor` first. It reports the Python, compiler,
  config and network state the CLI depends on.
- **`403` on submit** — the key is missing the `submissions:write` scope.
  `piko whoami` lists what it carries; mint a new one at `/settings/#api`.
- **Samples pass locally but the judge disagrees** — `piko test` compares after
  trimming trailing whitespace. If the problem needs a looser check, set
  `"checker"` in `piko.json` (`"unordered"`, or
  `{"kind": "float", "tolerance": 1e-6}`), or write a `checker.py` with
  `piko case --checker`.
- **Stale statement** — `piko cache --clear`.
