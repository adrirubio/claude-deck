"""Kernel-derived peer resolution (spec section 3.3)."""

import pytest

from app.utils import peer_process


def test_format_endpoint_ipv4():
    assert peer_process.format_endpoint("127.0.0.1", 8000) == "0100007F:1F40"


def test_format_endpoint_ipv6():
    assert peer_process.format_endpoint("::1", 8000) == (
        "00000000000000000000000001000000:1F40"
    )


def test_format_endpoint_rejects_a_hostname():
    """A non-literal host has no /proc/net representation, and must not be guessed at."""
    assert peer_process.format_endpoint("testclient", 123) is None


_HEADER = (
    "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when"
    " retrnsmt   uid  timeout inode\n"
)
_TAIL = "00000000:00000000 00:00000000 00000000  1000        0"

# The two mirror-image rows a single loopback connection produces, plus the
# backend's listening socket. 85D9 = 34265 (the caller), 85E8 = 34280 (us).
_TCP_TABLE = (
    _HEADER
    + f"   0: 0100007F:85E8 00000000:0000 0A {_TAIL} 39993299 1 0 20 0 0 10 0\n"
    + f"   1: 0100007F:85D9 0100007F:85E8 01 {_TAIL} 39993300 1 0 20 0 0 10 -1\n"
    + f"   2: 0100007F:85E8 0100007F:85D9 01 {_TAIL} 39993301 1 0 20 0 0 10 -1\n"
)

_STAT = (
    "1234 (claude with spaces) S 1200 1234 1234 0 -1 4194304 900 0 0 0 5 2 0 0"
    " 20 0 12 0 120913170 "
    + " ".join(["0"] * 30)
    + "\n"
)


@pytest.fixture
def tcp_table(tmp_path, monkeypatch):
    table = tmp_path / "tcp"
    table.write_text(_TCP_TABLE)
    monkeypatch.setattr(peer_process, "_PROC_NET_TABLES", ((str(table), None),))
    return table


def test_find_socket_inode_matches_the_local_address_column(tcp_table):
    """The caller's own socket has the caller's address in local_address.

    Matching rem_address instead would return 39993301 -- the backend's own
    accepted socket -- and resolve every caller to the backend's pid, binding
    every session to whatever pane the backend happens to run in.
    """
    assert peer_process.find_socket_inode("127.0.0.1", 34265) == 39993300


def test_find_socket_inode_ignores_a_listening_socket(tcp_table):
    """Row 0 has our port in local_address but is state 0A (LISTEN)."""
    assert peer_process.find_socket_inode("127.0.0.1", 34280, local_port=34265) == 39993301
    assert peer_process.find_socket_inode("127.0.0.1", 9999) is None


def test_find_socket_inode_disambiguates_on_the_local_port(tcp_table):
    """A wrong backend port must not match, even with the right caller port."""
    assert peer_process.find_socket_inode("127.0.0.1", 34265, local_port=34280) == 39993300
    assert peer_process.find_socket_inode("127.0.0.1", 34265, local_port=9999) is None


def test_read_proc_stat_survives_a_command_name_containing_spaces(tmp_path, monkeypatch):
    """The comm field is parenthesised and may contain spaces and parens.

    Splitting the whole line would misalign every field after it, so the parse
    starts after the LAST close-paren. One parse yields both fields we need.
    """
    proc = tmp_path / "1234"
    proc.mkdir()
    (proc / "stat").write_text(_STAT)
    monkeypatch.setattr(peer_process, "_PROC_ROOT", str(tmp_path))
    assert peer_process.read_proc_stat(1234) == (1200, "120913170")


def test_read_proc_stat_returns_none_for_a_dead_pid(tmp_path, monkeypatch):
    monkeypatch.setattr(peer_process, "_PROC_ROOT", str(tmp_path))
    assert peer_process.read_proc_stat(999999) is None


def test_list_tmux_pane_pids_parses_the_format_string(monkeypatch):
    output = "%3 159009 team:0.0\n%0 149168 team:0.1\n\n"
    monkeypatch.setattr(peer_process, "_run_tmux", lambda *args, **kwargs: output)
    assert peer_process.list_tmux_pane_pids() == {159009: "team:0.0", 149168: "team:0.1"}


def test_list_tmux_pane_pids_is_empty_when_tmux_is_absent(monkeypatch):
    monkeypatch.setattr(peer_process, "_run_tmux", lambda *args, **kwargs: None)
    assert peer_process.list_tmux_pane_pids() == {}


def test_resolve_peer_pane_walks_ppids_up_to_a_pane(monkeypatch):
    """The MCP shim is a grandchild of the pane, not the pane itself."""
    tree = {5000: (4000, "aaa"), 4000: (3000, "bbb"), 3000: (1, "ccc")}
    monkeypatch.setattr(
        peer_process, "find_socket_inode", lambda host, port, local_port=None: 77
    )
    monkeypatch.setattr(peer_process, "find_pid_for_inode", lambda inode: 5000)
    monkeypatch.setattr(peer_process, "read_proc_stat", lambda pid: tree.get(pid))
    monkeypatch.setattr(peer_process, "list_tmux_pane_pids", lambda: {3000: "team:0.2"})

    pane = peer_process.resolve_peer_pane("127.0.0.1", 36253)
    assert pane is not None
    assert (pane.pane_pid, pane.pane_proc_start, pane.tmux_target, pane.peer_pid) == (
        3000,
        "ccc",
        "team:0.2",
        5000,
    )


def test_resolve_peer_pane_is_none_when_no_ancestor_is_a_pane(monkeypatch):
    tree = {5000: (1, "aaa")}
    monkeypatch.setattr(
        peer_process, "find_socket_inode", lambda host, port, local_port=None: 77
    )
    monkeypatch.setattr(peer_process, "find_pid_for_inode", lambda inode: 5000)
    monkeypatch.setattr(peer_process, "read_proc_stat", lambda pid: tree.get(pid))
    monkeypatch.setattr(peer_process, "list_tmux_pane_pids", lambda: {3000: "team:0.2"})
    assert peer_process.resolve_peer_pane("127.0.0.1", 36253) is None


def test_resolve_peer_pane_is_none_when_the_socket_is_gone(monkeypatch):
    """The TIME_WAIT case: no inode, therefore no pane. Never guess."""
    monkeypatch.setattr(
        peer_process, "find_socket_inode", lambda host, port, local_port=None: None
    )
    assert peer_process.resolve_peer_pane("127.0.0.1", 36253) is None


def test_pane_is_alive_distinguishes_gone_from_unobservable(tmp_path, monkeypatch):
    """Three-valued on purpose: gone means prune, unobservable means keep."""
    proc = tmp_path / "1234"
    proc.mkdir()
    (proc / "stat").write_text(_STAT)
    monkeypatch.setattr(peer_process, "_PROC_ROOT", str(tmp_path))

    assert peer_process.pane_is_alive(1234, "120913170") is True
    assert peer_process.pane_is_alive(1234, "99999999") is False
    assert peer_process.pane_is_alive(4321, "120913170") is False


def test_pane_is_alive_is_none_when_proc_cannot_be_read(monkeypatch):
    def _boom(pid):
        raise PermissionError("no")

    monkeypatch.setattr(peer_process, "read_proc_stat", _boom)
    assert peer_process.pane_is_alive(1234, "120913170") is None
