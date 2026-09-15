from hydrostudy import doctor


def test_doctor_offline_passes(capsys):
    rows = doctor.run(network=False)
    statuses = {name: st for st, name, _ in rows}
    assert statuses["python"] == "PASS"
    assert all(statuses[f"package {m}"] == "PASS" for m in doctor.REQUIRED)
    assert doctor.main(network=False) == 0
    out = capsys.readouterr().out
    assert "Environment OK" in out and "--network" in out


def test_doctor_host_check_reports_not_raises(monkeypatch):
    import urllib.request

    def boom(*a, **k):
        raise OSError("blocked")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    rows = doctor._check_hosts(timeout=1)
    assert rows and all(st == "WARN" for st, _, _ in rows)
