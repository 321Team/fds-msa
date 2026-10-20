// 엔드페이지 동작 — 같은 Route host의 경로만 부른다(token·CORS 없음).
// /end/meta/*는 Downward API 파일(Pod 이름, 거래 버튼 표시 여부)이다.
// 거래 버튼 표시는 화면 편의일 뿐 보안 통제가 아니다. API(/api)는 Route로 원래 공개돼 있다.
// 집계판·규칙 보드 숫자는 이 브라우저에서 보낸 요청만 센다(서버 지표를 조회하지 않음).
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var busy = false;
  // 발표 모드(?mode=present): 녹화·라이브 시연용 스크롤 없는 한 화면 배치. 배치만 바뀌고 동작은 같다.
  var present = new URLSearchParams(location.search).get("mode") === "present";
  if (present) { document.body.classList.add("present"); }
  var stats = { sent: 0, hit: 0, ms: 0, n: 0, blocked: {} };

  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  function getText(path) {
    return fetch(path, { cache: "no-store" }).then(function (r) {
      if (!r.ok) { throw new Error(String(r.status)); }
      return r.text();
    });
  }

  function runId() {
    // KST yyyymmddHHMM — 시험 계정 관례 SIM_<목적>_<RUN>_<ID>(#11 결정안 5887795557)
    var d = new Date(Date.now() + 9 * 3600 * 1000).toISOString();
    return d.slice(0, 16).replace(/[-:T]/g, "");
  }

  function chip(text, kind) {
    var s = document.createElement("span");
    s.className = "chip " + kind;
    s.textContent = text;
    return s;
  }

  function bump(el) {
    el.classList.remove("bump");
    void el.offsetWidth; // 같은 애니메이션을 다시 시작한다
    el.classList.add("bump");
  }

  // 화면에는 규칙 번호(R01 등) 대신 이름을 쓴다 — 번호는 팀 내부 용어라 처음 보는 사람이 모른다.
  var RULE_NAMES = { R01: "쪼개기 인출", R02: "고액 거래", R04: "심야 고액", R07: "분산 이체" };
  function ruleName(id) { return RULE_NAMES[id] || id; }
  function ruleDetail(r) {
    return ruleName(r.rule_id) + (r.detail ? " · " + String(r.detail).replace(/threshold/g, "기준") : "");
  }

  // ---------- 탐지·차단 배너(2초) ----------
  var bannerTimer = null;
  function showBanner(text, kind) {
    var b = $("banner");
    $("banner-text").textContent = text;
    b.className = "banner " + kind;
    b.hidden = false;
    void b.offsetWidth;
    b.classList.add("show");
    clearTimeout(bannerTimer);
    bannerTimer = setTimeout(function () { b.hidden = true; }, 2200);
  }

  // ---------- 시연용 가상 잔액(브라우저 안에서만 계산, 서버·DB에 잔액 없음) ----------
  var START_BALANCE = 5000000;
  var balance = START_BALANCE;
  function won(n) { return n.toLocaleString("ko-KR") + "원"; }
  function resetBalance() {
    balance = START_BALANCE;
    $("vbal-amt").textContent = won(balance);
    var d = $("vbal-delta");
    d.textContent = "시작 " + won(START_BALANCE);
    d.className = "vbal-delta";
  }
  function moveBalance(type, amount, label, detected) {
    var sign = type === "deposit" ? 1 : -1;
    balance += sign * amount;
    $("vbal-amt").textContent = won(balance);
    bump($("vbal-amt"));
    var d = $("vbal-delta");
    d.textContent = (sign > 0 ? "+" : "−") + won(amount) + " · " + label + (detected ? " · 탐지" : "");
    d.className = "vbal-delta " + (detected ? "hit" : sign > 0 ? "in" : "out");
  }

  // ---------- 하단 띠: 접속 주소·KST 시각(녹화 화면에 ROSA 주소와 시각을 남긴다) ----------
  function tickClock() {
    var d = new Date(Date.now() + 9 * 3600 * 1000).toISOString();
    $("live-clock").textContent = d.slice(0, 10) + " " + d.slice(11, 19);
  }

  // ---------- 1. 살아 있는 구조 그림 ----------
  function setDot(nodeId, state) {
    var dot = document.querySelector("#" + nodeId + " .dot");
    if (dot) { dot.className = "dot" + (state ? " " + state : ""); }
  }

  function setVpn(state) { $("n-vpn").className = "link vpn" + (state ? " " + state : ""); }

  // /readyz는 transaction-api가 DB ping까지 해 본 결과다.
  // 200 = 라우터·API·VPN·DB 모두 응답 / JSON 503 = API는 살아 있고 DB(또는 VPN)가 실패
  // 그 밖의 응답 = 라우터가 API에 닿지 못함 / 응답 없음 = 라우터까지도 확인 불가
  function loadReady() {
    return fetch("/readyz", { cache: "no-store" })
      .then(function (r) {
        var isJson = (r.headers.get("Content-Type") || "").indexOf("application/json") >= 0;
        setDot("n-router", "ok");
        if (r.status === 200) {
          setDot("n-api", "ok"); setVpn("ok"); setDot("n-db", "ok");
          $("topo-note").textContent = "GET /readyz → 200 · 라우터, 거래 API, VPN, 사내 DB가 모두 응답합니다.";
        } else if (r.status === 503 && isJson) {
          setDot("n-api", "ok"); setVpn("bad"); setDot("n-db", "bad");
          $("topo-note").textContent = "GET /readyz → 503 · 거래 API는 살아 있지만 사내 DB에 닿지 못합니다(VPN 또는 DB).";
        } else {
          setDot("n-api", "bad"); setVpn(""); setDot("n-db", "");
          $("topo-note").textContent = "GET /readyz → " + r.status + " · 라우터가 거래 API에 닿지 못합니다.";
        }
      })
      .catch(function () {
        ["n-router", "n-api", "n-db"].forEach(function (id) { setDot(id, ""); });
        setVpn("");
        $("topo-note").textContent = "응답 없음 · 구간 상태를 확인할 수 없습니다.";
      });
  }

  // fds-engine은 직접 조회하지 않는다. 마지막 거래 응답의 판정 생략(fail-open) 여부로 칠한다.
  function markEngine(skipped) { setDot("n-engine", skipped ? "warn" : "ok"); }

  function flashTopo() {
    var ids = ["n-router", "n-api", "n-engine", "n-db"];
    ids.forEach(function (id, i) {
      setTimeout(function () { $(id).classList.add("flash"); }, 110 * i);
      setTimeout(function () { $(id).classList.remove("flash"); }, 110 * i + 500);
    });
  }

  // ---------- 3. 집계판 ----------
  function renderStats() {
    $("st-sent").textContent = String(stats.sent);
    $("st-hit").textContent = String(stats.hit);
    $("st-block").textContent = Object.keys(stats.blocked).length + " / 3";
    $("st-ms").textContent = stats.n ? Math.round(stats.ms / stats.n) + " ms" : "–";
  }

  // ---------- 2. 거래 경로 + 규칙 보드 ----------
  function animatePath() {
    var steps = document.querySelectorAll("#path li");
    steps.forEach(function (li) { li.classList.remove("on"); });
    var end = $("path-end");
    end.className = "path-end";
    end.textContent = "판정";
    steps.forEach(function (li, i) {
      if (li === end) { return; }
      setTimeout(function () { li.classList.add("on"); }, 110 * (i + 1));
    });
    flashTopo();
  }

  function markPathEnd(kind, text) {
    var end = $("path-end");
    end.className = "path-end end-" + kind;
    end.textContent = text;
  }

  function lightRules(ruleIds) {
    ruleIds.forEach(function (id) {
      var card = document.querySelector('.rule[data-rule="' + id + '"]');
      var count = $("rc-" + id);
      if (!card || !count) { return; }
      count.textContent = String(Number(count.textContent) + 1);
      card.classList.add("lit");
      card.classList.remove("flash");
      void card.offsetWidth;
      card.classList.add("flash");
    });
  }

  // 시나리오 값은 금감원 공개 사례 대응표(FSS-01·03·04·06)의 시험 거래를 따른다. 버튼에는 규칙 번호를 쓰지 않는다.
  // R01·R07은 같은 계정의 이전 거래만 세므로(context.py) 4번째 거래에서 걸린다.
  function kstTodayAt(hhmm) {
    var d = new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10);
    return d + "T" + hhmm + ":00+09:00";
  }
  function repeat(step, n) { var a = []; for (var i = 0; i < n; i += 1) { a.push(step); } return a; }
  var SCENARIOS = {
    N01: { name: "정상 입금", steps: [{ type: "deposit", amount: 10000 }] },
    R02: { name: "고액 이체 · FSS-01", steps: [{ type: "transfer", amount: 3500000 }] },
    R01: { name: "쪼개기 인출 · FSS-03", steps: repeat({ type: "withdrawal", amount: 900000 }, 4) },
    R07: { name: "분산 이체 · FSS-04", steps: repeat({ type: "transfer", amount: 700000 }, 4) },
    R04: { name: "심야 이체 · 팀 규칙", steps: [{ type: "transfer", amount: 1500000, at: "02:30" }] }
  };

  function postOnce(payload) {
    var t0 = performance.now();
    return fetch("/api/v1/transactions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).then(function (r) {
      var ms = Math.round(performance.now() - t0);
      return r.json().catch(function () { return null; }).then(function (b) { return { status: r.status, body: b, ms: ms }; });
    }, function () { return { status: 0, body: null, ms: 0 }; });
  }

  function resultLine(step, total, res) {
    var line = document.createElement("div");
    line.className = "step-line";
    var head = total > 1 ? step + "/" + total + " " : "";
    var body = res.body;
    if (res.status === 201 && body) {
      var hits = (body.fds_rules || []).filter(function (r) { return r && r.triggered; });
      if (body.fds_evaluation_skipped) {
        line.appendChild(chip(head + "판정 생략 (fail-open)", "warn"));
      } else if (body.fds_detected) {
        line.appendChild(chip(head + "의심거래 탐지", "warn"));
      } else {
        line.appendChild(chip(head + "정상", "ok"));
      }
      line.appendChild(document.createTextNode(
        (hits.length ? hits.map(ruleDetail).join(" / ") : "걸린 규칙 없음")
        + " · " + res.ms + " ms"));
    } else {
      line.appendChild(chip(head + "실패", "bad"));
      line.appendChild(document.createTextNode("HTTP " + res.status));
    }
    return line;
  }

  function applyTxResult(res) {
    if (res.status !== 201 || !res.body) { markPathEnd("bad", "실패"); return; }
    stats.sent += 1; bump($("st-sent"));
    stats.ms += res.ms; stats.n += 1;
    markEngine(res.body.fds_evaluation_skipped);
    var hits = (res.body.fds_rules || []).filter(function (r) { return r && r.triggered; })
      .map(function (r) { return r.rule_id; });
    if (res.body.fds_evaluation_skipped) {
      markPathEnd("skip", "판정 생략");
    } else if (res.body.fds_detected) {
      stats.hit += 1; bump($("st-hit"));
      markPathEnd("hit", "탐지 · " + hits.map(ruleName).join("·"));
      lightRules(hits);
    } else {
      markPathEnd("ok", "정상");
    }
    renderStats();
  }

  function runScenario(id) {
    var s = SCENARIOS[id];
    var total = s.steps.length;
    var box = $("result");
    box.className = "";
    box.textContent = "";
    // 누를 때마다 새 계정 — 같은 분에 다시 눌러도 이전 이력이 섞이지 않게 한다.
    var account = "SIM_end_" + runId() + "_" + id + "-" + Math.random().toString(16).slice(2, 6);
    var acct = document.createElement("div");
    acct.className = "mono muted";
    acct.textContent = s.name + " · 계정 " + account;
    box.appendChild(acct);
    resetBalance();
    var step = 0;
    function next() {
      step += 1;
      if (step > total) { return Promise.resolve(); }
      var st = s.steps[step - 1];
      animatePath();
      var payload = { account_id: account, amount: st.amount, currency: "KRW",
        transaction_type: st.type, source_ip: "198.51.100.10" };
      if (st.at) { payload.occurred_at = kstTodayAt(st.at); }
      // 이전 거래가 저장된 뒤에 다음 거래를 보낸다(이력 기반 규칙).
      return postOnce(payload).then(function (res) {
        return sleep(700).then(function () {
          box.appendChild(resultLine(step, total, res));
          applyTxResult(res);
          if (res.status === 201 && res.body) {
            var hits = (res.body.fds_rules || []).filter(function (r) { return r && r.triggered; })
              .map(function (r) { return r.rule_id; });
            moveBalance(st.type, st.amount, total > 1 ? step + "/" + total : s.name.split(" · ")[0], Boolean(res.body.fds_detected));
            if (res.body.fds_evaluation_skipped) {
              showBanner("판정 생략 · 거래는 저장됨", "warn");
            } else if (res.body.fds_detected) {
              showBanner("의심거래 탐지 · " + hits.map(ruleName).join("·"), "hit");
            }
          }
          return res.status === 201 ? next() : null;
        });
      });
    }
    return next();
  }

  // ---------- 보안 확인 ----------
  // p2e2e B2의 X01·N06·N07과 같은 판정. 막히면(200/201이 아니면) 통과. N06·N07은 422로 저장되지 않는다.
  var CHECKS = {
    X01: { want: "200이 아님", stopAt: 1, where: "ROSA 라우터에서 차단", why: "열려 있지 않은 경로", name: "내부 지표 엿보기", run: function () {
      return fetch("/metrics", { cache: "no-store" }).then(function (r) {
        return { blocked: r.status !== 200 && r.status < 500, unknown: r.status >= 500, text: "GET /metrics → " + r.status };
      });
    } },
    N06: { want: "422", stopAt: 2, where: "transaction-api 입력 검증에서 차단", why: "없는 거래 종류", name: "없는 거래 종류", run: function () {
      return postOnce({ account_id: "SIM_end_" + runId() + "_N06", amount: 10000, currency: "KRW",
        transaction_type: "refund", source_ip: "198.51.100.10" }).then(function (res) {
        return { blocked: res.status === 422, unknown: res.status === 0 || res.status >= 500, text: "POST transaction_type=refund → " + res.status };
      });
    } },
    N07: { want: "422", stopAt: 2, where: "transaction-api 입력 검증에서 차단", why: "필수 값(금액) 누락", name: "금액 빠진 거래", run: function () {
      return postOnce({ account_id: "SIM_end_" + runId() + "_N07", currency: "KRW",
        transaction_type: "deposit", source_ip: "198.51.100.10" }).then(function (res) {
        return { blocked: res.status === 422, unknown: res.status === 0 || res.status >= 500, text: "POST amount 없음 → " + res.status };
      });
    } }
  };

  // 요청이 지나간 계층은 파랑, 막힌 계층은 빨강(차단), 그 뒤는 흐리게 — 어디서 막혔는지 한눈에 보이게 한다.
  function paintLane(stopAt, blocked) {
    var nodes = Array.prototype.slice.call(document.querySelectorAll("#sec-lane li"));
    var last = blocked ? stopAt : nodes.length - 1;
    nodes.forEach(function (li, i) {
      setTimeout(function () {
        li.className = i < last || (!blocked && i === last) ? "pass" : i === last ? "stop" : "dim";
      }, 180 * (i + 1));
    });
    return 180 * (nodes.length + 1);
  }

  function showVerdict(c, r) {
    var box = $("sec-verdict");
    box.hidden = false;
    box.className = "verdict" + (r.blocked ? "" : " bad");
    $("sec-title").textContent =
      r.unknown ? "확인 불가 — " + c.name : r.blocked ? c.where + " — " + c.why : "기대한 차단 응답이 아님 (기대 " + c.want + ")";
    $("sec-detail").textContent = r.text;
  }

  // 보안 확인 보드 카드 상태: running(파랑 깜빡임) → lit(초록, 차단) / bad(빨강, 예상과 다름)
  function setTile(tile, state, label) {
    tile.className = "sec-tile" + (state ? " " + state : "");
    tile.querySelector(".sec-tile-state").textContent = label;
    if (state === "lit" || state === "bad") {
      void tile.offsetWidth; // 같은 애니메이션을 다시 시작한다
      tile.classList.add("flash");
    }
  }

  function runCheck(id) {
    var c = CHECKS[id];
    var tile = document.querySelector('#sec-score [data-score="' + id + '"]');
    var button = document.querySelector('#sec-card button[data-check="' + id + '"]');
    document.querySelectorAll("#sec-lane li").forEach(function (li) { li.className = ""; });
    $("sec-verdict").hidden = true;
    setTile(tile, "running", "시도 중…");
    button.classList.add("active");
    return c.run()
      .then(function (r) {
        var code = (r.text.match(/→ (\d+)/) || [])[1] || "";
        if (r.unknown) {
          showVerdict(c, r);
          setTile(tile, "bad", "확인 불가" + (code ? " · " + code : ""));
          delete stats.blocked[id]; renderStats();
          return;
        }
        return sleep(paintLane(c.stopAt, r.blocked)).then(function () {
          showVerdict(c, r);
          setTile(tile, r.blocked ? "lit" : "bad", (r.blocked ? "차단됨" : "기대와 다름") + (code ? " · " + code : ""));
          if (r.blocked) { showBanner("보안 차단 · " + c.where.replace(/에서 차단$/, "") + " — " + c.why, "block"); }
          if (r.blocked) { stats.blocked[id] = true; } else { delete stats.blocked[id]; }
          bump($("st-block"));
          renderStats();
        });
      }, function () {
        showVerdict(c, { blocked: false, unknown: true, text: "응답 없음 — 확인 불가" });
        setTile(tile, "bad", "확인 불가");
        delete stats.blocked[id]; renderStats();
      })
      .then(function () { button.classList.remove("active"); });
  }

  // ---------- 4. 자동 시연 ----------
  var AUTO = [
    { kind: "tx", id: "N01" }, { kind: "tx", id: "R02" }, { kind: "tx", id: "R01" },
    { kind: "tx", id: "R07" }, { kind: "tx", id: "R04" },
    { kind: "check", id: "X01" }, { kind: "check", id: "N06" }, { kind: "check", id: "N07" }
  ];

  function setBusy(on) {
    busy = on;
    document.querySelectorAll("#tx-card button, #sec-card button").forEach(function (b) { b.disabled = on; });
  }

  function guard(fn) {
    return function () {
      if (busy) { return; }
      setBusy(true);
      Promise.resolve().then(fn).catch(function () { return null; }).then(function () { setBusy(false); });
    };
  }

  function label(step) {
    return step.kind === "tx" ? SCENARIOS[step.id].name : "보안 시도 · " + CHECKS[step.id].name;
  }

  function runAuto() {
    var status = $("auto-status");
    var i = 0;
    function next() {
      if (i >= AUTO.length) {
        status.textContent = "자동 시연 끝 · 거래 " + stats.sent + "건, 탐지 " + stats.hit + "건, 보안 차단 "
          + Object.keys(stats.blocked).length + "/3";
        return Promise.resolve();
      }
      var step = AUTO[i];
      i += 1;
      status.textContent = "자동 시연 " + i + "/" + AUTO.length + " · " + label(step);
      if (!present) {
        $(step.kind === "tx" ? "tx-card" : "sec-card").scrollIntoView({ behavior: "smooth", block: "center" });
      }
      return sleep(600)
        .then(function () { return step.kind === "tx" ? runScenario(step.id) : runCheck(step.id); })
        .then(function () { return sleep(1500); })
        .then(next);
    }
    return next();
  }

  // ---------- 스위치(녹화 중에만 on) ----------
  function loadTxFlag() {
    function show(on) {
      ["tx-card", "sec-card", "stats"].forEach(function (id) { $(id).hidden = !on; });
    }
    getText("/end/meta/tx-demo")
      .then(function (t) { show(t.trim() === "on"); })
      .catch(function () { show(false); });
  }

  // ---------- 연결 ----------
  $("auto").addEventListener("click", guard(runAuto));
  document.querySelectorAll("#tx-card button[data-scenario]").forEach(function (b) {
    b.addEventListener("click", guard(function () { return runScenario(b.getAttribute("data-scenario")); }));
  });
  document.querySelectorAll("#sec-card button[data-check]").forEach(function (b) {
    b.addEventListener("click", guard(function () { return runCheck(b.getAttribute("data-check")); }));
  });

  // 녹화용 단축키(화면에는 표시하지 않음): 1~5 거래, Q·W·E 보안 시도, A 자동 시연. 버튼이 보일 때만.
  var KEYS = { "1": "N01", "2": "R02", "3": "R01", "4": "R07", "5": "R04", q: "X01", w: "N06", e: "N07" };
  document.addEventListener("keydown", function (ev) {
    if (ev.ctrlKey || ev.metaKey || ev.altKey || $("tx-card").hidden) { return; }
    var k = ev.key.toLowerCase();
    var target = k === "a" ? $("auto")
      : KEYS[k] ? document.querySelector('[data-scenario="' + KEYS[k] + '"], [data-check="' + KEYS[k] + '"]') : null;
    if (target) { ev.preventDefault(); target.click(); }
  });

  $("live-host").textContent = location.host;
  tickClock();
  setInterval(tickClock, 1000);
  resetBalance();
  loadReady();
  loadTxFlag();
  renderStats();
  // 구간 상태는 10초마다 다시 본다(Pod 삭제·DB 장애 장면에서 바로 바뀌게).
  setInterval(function () { if (!document.hidden) { loadReady(); } }, 10000);
})();
