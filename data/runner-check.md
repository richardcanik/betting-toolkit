# Dostupnosť Niké z GitHub runnera

Posledný pokus: 2026-09-14 18:37 UTC

```
Traceback (most recent call last):
  File "/home/runner/work/betting-toolkit/betting-toolkit/tools/nike_odds.py", line 453, in <module>
    main()
  File "/home/runner/work/betting-toolkit/betting-toolkit/tools/nike_odds.py", line 391, in main
    run(args)
  File "/home/runner/work/betting-toolkit/betting-toolkit/tools/nike_odds.py", line 398, in run
    context = client_context()
              ^^^^^^^^^^^^^^^^
  File "/home/runner/work/betting-toolkit/betting-toolkit/tools/nike_odds.py", line 100, in client_context
    with urllib.request.urlopen(req, timeout=30) as resp:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.12.14/x64/lib/python3.12/urllib/request.py", line 215, in urlopen
    return opener.open(url, data, timeout)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.12.14/x64/lib/python3.12/urllib/request.py", line 521, in open
    response = meth(req, response)
               ^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.12.14/x64/lib/python3.12/urllib/request.py", line 630, in http_response
    response = self.parent.error(
               ^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.12.14/x64/lib/python3.12/urllib/request.py", line 559, in error
    return self._call_chain(*args)
           ^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.12.14/x64/lib/python3.12/urllib/request.py", line 492, in _call_chain
    result = func(*args)
             ^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.12.14/x64/lib/python3.12/urllib/request.py", line 639, in http_error_default
    raise HTTPError(req.full_url, code, msg, hdrs, fp)
urllib.error.HTTPError: HTTP Error 403: Forbidden
ZLYHALO
```
