BASH = """\
_piko_complete() {
  local cur="${COMP_WORDS[COMP_CWORD]}"
  local reply
  reply="$(piko __complete "${COMP_WORDS[@]:1:COMP_CWORD-1}" 2>/dev/null)"
  COMPREPLY=( $(compgen -W "${reply}" -- "${cur}") )
}
complete -F _piko_complete piko
"""

ZSH = """\
#compdef piko
_piko() {
  local -a words
  words=(${(f)"$(piko __complete ${(@)words[2,CURRENT-1]} 2>/dev/null)"})
  compadd -- ${=words}
}
compdef _piko piko
"""

FISH = """\
function __piko_complete
  piko __complete (commandline -opc)[2..-1] 2>/dev/null
end
complete -c piko -f -a '(__piko_complete)'
"""

SHELLS = {"bash": BASH, "zsh": ZSH, "fish": FISH}

def candidates(words, commands, languages):
    if not words:
        return sorted(commands)

    verb,rest = words[0], words[1:]
    if verb not in commands:
        return sorted(commands)

    last = rest[-1] if rest else ""
    if last in ("--lang", "--difficulty"):
        return (sorted(languages) if last == "--lang"
                else ["easy", "medium", "hard"])


    out = []
    if verb in ("show","get","submit","editorial","open","hint"):
        out += cached_slugs()
    if verb in ("track",):
        out += cached_slugs(kind="tracks")
    return sorted(set(out))

def cached_slugs(kind="problems"):
    import json
    from . import config

    found = []
    if not config.CACHE.is_dir():
        return found
    for path in config.CACHE.glob("*.json"):
        try:
            body = json.loads(path.read_text(encoding="utf-8")).get("body")
        except (OSError, ValueError):
            continue
        if not isinstance(body, dict):
            continue
        if isinstance(body.get("items"), list):
            found += [r["slug"] for r in body["items"]
                      if isinstance(r, dict) and r.get("slug")]
        elif body.get("slug"):
            found.append(body["slug"])
    return found

