import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.judge import TestCase, judge, verdicts as V

CASES = [
    ("python", "print(sum(map(int, input().split())))", "2 3\n", "5\n"),
    ("cpp", '#include <iostream>\nint main(){int a,b;std::cin>>a>>b;'
            'std::cout<<a+b<<"\\n";}', "2 3\n", "5\n"),
    ("java", "import java.util.*;public class Main{public static void main(String[] a){"
             "Scanner s=new Scanner(System.in);System.out.println(s.nextInt()+s.nextInt());}}",
     "2 3\n", "5\n"),
]

for lang, src, stdin, expected in CASES:
    r = judge(src, lang, [TestCase(stdin=stdin, expected_stdout=expected, is_sample=True)])
    print("%-7s %-22s %sms  %s" % (
        lang, V.LABELS.get(r.verdict, r.verdict), r.max_time_ms,
        (r.compile_output or r.message or "")[:70]))

# Hostile-input checks - each should be contained, not crash the host.
HOSTILE = [
    ("python", "while True: pass", V.TLE),
    ("python", "x = ' ' * (10**9)", V.MLE),
    ("python", "import sys; sys.exit(1)", V.RE),
    ("python", "import socket; socket.create_connection(('1.1.1.1',80),2)", V.RE),
    ("cpp", "int main(){ return", V.CE),
]
for lang, src, want in HOSTILE:
    r = judge(src, lang, [TestCase(stdin="", expected_stdout="")], time_limit_sec=2.0)
    print("%-7s expected %-24s got %s" % (lang, want, r.verdict))
