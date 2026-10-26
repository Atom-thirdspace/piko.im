import os
import click

DANGEROUS = {
    "seed-catalog", "gen-bulk", "gen-llm", "gen-template",
    "import-problem", "import-problems", "arena-import", "arena-pools",
    "arena-bosses", "season-open", "season-roll", "rivals-roll",
    "raids-expire", "notify-prune", "notify-streaks", "traffic-prune",
    "oauth-prune", "judge-prune", "judge-drain",
    "backfill-achievements", "index-fingerprints",
}

OVERRIDE = "PIKO_ALLOW_PROD"

def environment():
    return (os.environ.get("PIKO_ENV") or "production").strip().lower()

def database_host():
    url = os.environ.get("DATABASE_URL") or ""
    return url.split("@")[-1].split("/")[0] if "@" in url else "unknown"

def install(app):
    @app.cli.resultcallback()
    def _noop(*args, **kwargs):
        return None

    group = app.cli
    original = group.get_command

    def guarded(ctx, name):
        command = original(ctx, name)
        if command is None or name not in DANGEROUS:
            return command

        original_invoke = command.invoke

        def invoke(sub_ctx):
            if environment() != "production":
                return original_invoke(sub_ctx)
            if os.environ.get(OVERRIDE) == "1":
                click.echo("running %r against PRODUCTION (%s)"
                           % (name, database_host()), err=True)
                return original_invoke(sub_ctx)
            raise click.ClickException(
                "%r writes to the database and PIKO_ENV is 'production' "
                "(%s).\nSet PIKO_ENV=development with a dev DATABASE_URL, "
                "or export %s=1 if you really mean production."
                % (name, database_host(), OVERRIDE))

        command.invoke = invoke
        return command
    group.get_command = guarded