import platform
import shutil
import subprocess

def notify(title, body=""):
    system = platform.system()
    try:
        if system == "Darwin":
            script = 'display notification %s with title %s' % (
                _applescript(body), _applescript(title))
            subprocess.run(["osascript", "-e", script], timeout=5,
                           capture_output=True)
            return True
        if system == "Linux" and shutil.which("notify-send"):
            subprocess.run(["notify-send", title, body], timeout=5,
                           capture_output=True)
            return True
        if system == "Windows":
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 _toast(title, body)], timeout=10, capture_output=True)
            return True
    except (OSError, subprocess.SubprocessError):
        return False
    return False

def _applescript(text):
    return '"%s"' % (text or "").replace("\\", "\\\\").replace('"', '\\"')


def _toast(title, body):
    safe = lambda t: (t or "").replace("'", "''")
    return (
        "[Windows.UI.Notifications.ToastNotificationManager,"
        "Windows.UI.Notifications,ContentType=WindowsRuntime] > $null;"
        "$x=[Windows.UI.Notifications.ToastNotificationManager]::"
        "GetTemplateContent("
        "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
        "$t=$x.GetElementsByTagName('text');"
        "$t.Item(0).AppendChild($x.CreateTextNode('%s')) > $null;"
        "$t.Item(1).AppendChild($x.CreateTextNode('%s')) > $null;"
        "[Windows.UI.Notifications.ToastNotificationManager]::"
        "CreateToastNotifier('Piko').Show("
        "[Windows.UI.Notifications.ToastNotification]::new($x))"
        % (safe(title), safe(body)))
