// 엔드페이지 동작 — 같은 Route host의 경로만 부른다(token·CORS 없음).
// /end/meta/*는 Downward API 파일(Pod 이름, 거래 버튼 표시 여부)이다.
// 거래 버튼 표시는 화면 편의일 뿐 보안 통제가 아니다. API(/api)는 Route로 원래 공개돼 있다.
// 집계판·규칙 보드 숫자는 이 브라우저에서 보낸 요청만 센다(서버 지표를 조회하지 않음).
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var busy = false;
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

  // ---------- 응답 Pod ----------
  function loadPod() {
    var el = $("pod");
    el.textContent = "확인 중…";
    getText("/end/meta/pod")
      .then(function (t) { el.textContent = t.trim() || "알 수 없음"; })
      .catch(function () { el.textContent = "알 수 없음"; });
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

  // 시나리오는 회귀 도구 tools/regression/rg.py의 케이스 구성과 같다(P02·P03·P04·P05).
  // R01·R07은 같은 계정의 이전 거래만 세므로(context.py) 4번째 거래에서 걸린다.
  function kstTodayAt(hhmm) {
    var d = new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10);
    return d + "T" + hhmm + ":00+09:00";
  }
  var SCENARIOS = {
    N01: { name: "정상 입금", type: "deposit", amount: 10000, count: 1 },
    R02: { name: "R02 고액", type: "deposit", amount: 3000000, count: 1 },
    R01: { name: "R01 연속 출금", type: "withdrawal", amount: 10000, count: 4 },
    R07: { name: "R07 분산 이체", type: "transfer", amount: 700000, count: 4 },
    R04: { name: "R04 심야", type: "deposit", amount: 1500000, count: 1, at: "02:30" }
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
        (hits.length ? hits.map(function (r) { return r.rule_id + " · " + (r.detail || ""); }).join(" / ") : "걸린 규칙 없음")
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
      markPathEnd("hit", "탐지 " + hits.join("·"));
      lightRules(hits);
    } else {
      markPathEnd("ok", "정상");
    }
    renderStats();
  }

  function runScenario(id) {
    var s = SCENARIOS[id];
    var box = $("result");
    box.className = "";
    box.textContent = "";
    // 누를 때마다 새 계정 — 같은 분에 다시 눌러도 이전 이력이 섞이지 않게 한다.
    var account = "SIM_end_" + runId() + "_" + id + "-" + Math.random().toString(16).slice(2, 6);
    var acct = document.createElement("div");
    acct.className = "mono muted";
    acct.textContent = s.name + " · 계정 " + account;
    box.appendChild(acct);
    var step = 0;
    function next() {
      step += 1;
      if (step > s.count) { return Promise.resolve(); }
      animatePath();
      var payload = { account_id: account, amount: s.amount, currency: "KRW",
        transaction_type: s.type, source_ip: "198.51.100.10" };
      if (s.at) { payload.occurred_at = kstTodayAt(s.at); }
      // 이전 거래가 저장된 뒤에 다음 거래를 보낸다(이력 기반 규칙).
      return postOnce(payload).then(function (res) {
        return sleep(700).then(function () {
          box.appendChild(resultLine(step, s.count, res));
          applyTxResult(res);
          return res.status === 201 ? next() : null;
        });
      });
    }
    return next();
  }

  // ---------- 보안 확인 ----------
  // p2e2e B2의 X01·N06·N07과 같은 판정. 막히면(200/201이 아니면) 통과. N06·N07은 422로 저장되지 않는다.
  var CHECKS = {
    X01: { want: "200이 아님", stopAt: 1, where: "ROSA 라우터에서 차단", why: "Route에 없는 경로", run: function () {
      return fetch("/metrics", { cache: "no-store" }).then(function (r) {
        return { blocked: r.status !== 200, text: "GET /metrics → " + r.status };
      });
    } },
    N06: { want: "422", stopAt: 2, where: "transaction-api 입력 검증에서 차단", why: "없는 거래 종류", run: function () {
      return postOnce({ account_id: "SIM_end_" + runId() + "_N06", amount: 10000, currency: "KRW",
        transaction_type: "refund", source_ip: "198.51.100.10" }).then(function (res) {
        return { blocked: res.status === 422, text: "POST transaction_type=refund → " + res.status };
      });
    } },
    N07: { want: "422", stopAt: 2, where: "transaction-api 입력 검증에서 차단", why: "필수 값(금액) 누락", run: function () {
      return postOnce({ account_id: "SIM_end_" + runId() + "_N07", currency: "KRW",
        transaction_type: "deposit", source_ip: "198.51.100.10" }).then(function (res) {
        return { blocked: res.status === 422, text: "POST amount 없음 → " + res.status };
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
      r.blocked ? c.where + " — " + c.why : "예상과 다름 — 요청이 통과했습니다 (기대 " + c.want + ")";
    $("sec-detail").textContent = r.text;
  }

  function runCheck(id) {
    var c = CHECKS[id];
    var score = document.querySelector('#sec-score [data-score="' + id + '"]');
    document.querySelectorAll("#sec-lane li").forEach(function (li) { li.className = ""; });
    $("sec-verdict").hidden = true;
    return c.run()
      .then(function (r) {
        return sleep(paintLane(c.stopAt, r.blocked)).then(function () {
          showVerdict(c, r);
          score.className = r.blocked ? "ok" : "bad";
          if (r.blocked) { stats.blocked[id] = true; } else { delete stats.blocked[id]; }
          bump($("st-block"));
          renderStats();
        });
      }, function () {
        showVerdict(c, { blocked: false, text: "응답 없음 — 확인 불가" });
        score.className = "bad";
      });
  }

  // ---------- 4. 자동 시연 ----------
  var AUTO = [
    { kind: "tx", id: "N01" }, { kind: "tx", id: "R02" }, { kind: "tx", id: "R01" },
    { kind: "tx", id: "R07" }, { kind: "tx", id: "R04" },
    { kind: "check", id: "X01" }, { kind: "check", id: "N06" }, { kind: "check", id: "N07" }
  ];

  function setBusy(on) {
    busy = on;
    document.querySelectorAll("#tx-card button, #sec-card button, #reload").forEach(function (b) { b.disabled = on; });
  }

  function guard(fn) {
    return function () {
      if (busy) { return; }
      setBusy(true);
      Promise.resolve().then(fn).catch(function () { return null; }).then(function () { setBusy(false); });
    };
  }

  function label(step) {
    return step.kind === "tx" ? SCENARIOS[step.id].name : step.id + " " + CHECKS[step.id].why;
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
      var card = $(step.kind === "tx" ? "tx-card" : "sec-card");
      card.scrollIntoView({ behavior: "smooth", block: "center" });
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
  $("reload").addEventListener("click", function () { loadPod(); loadReady(); });
  $("auto").addEventListener("click", guard(runAuto));
  document.querySelectorAll("#tx-card button[data-scenario]").forEach(function (b) {
    b.addEventListener("click", guard(function () { return runScenario(b.getAttribute("data-scenario")); }));
  });
  document.querySelectorAll("#sec-card button[data-check]").forEach(function (b) {
    b.addEventListener("click", guard(function () { return runCheck(b.getAttribute("data-check")); }));
  });

  loadPod();
  loadReady();
  loadTxFlag();
  renderStats();
  // 구간 상태는 10초마다 다시 본다(Pod 삭제·DB 장애 장면에서 바로 바뀌게).
  setInterval(function () { if (!document.hidden) { loadReady(); } }, 10000);
})();
