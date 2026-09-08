import React, { useState, useEffect, useRef, useMemo } from "react";

/* ────────────────────────────────────────────────────────────────
   Рабочий экран лота целиком: шапка, вкладки, подписи и правая
   панель процесса. Отделы в панели по умолчанию свёрнуты.
   Роль наверху — демо-переключатель, в продукте её даёт вход.
   ──────────────────────────────────────────────────────────────── */

const CSS = `
.tp{
  --ink:#0E1620; --ink2:#5C6B7A; --ink3:#93A0AC;
  --line:#E2E7EC; --line2:#EFF2F5;
  --bg:#F4F6F8; --card:#fff;
  --blue:#2A63E8; --blue-w:#EDF2FE; --blue-d:#1B49B8;
  --hot:#D0301C; --hot-w:#FCEDEA;
  --warm:#95560A; --warm-w:#FCF2E2;
  --ok:#0A7245; --ok-w:#E9F5EF;
  font-family:-apple-system,"SF Pro Text",Inter,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  color:var(--ink); -webkit-font-smoothing:antialiased; font-size:13px; line-height:1.45;
}
.tp *{box-sizing:border-box; margin:0; padding:0;}
.tp button{font:inherit; color:inherit; background:none; border:none; cursor:pointer; text-align:left;}
.tp button:focus-visible,.tp input:focus-visible,.tp select:focus-visible,.tp textarea:focus-visible{
  outline:2px solid var(--blue); outline-offset:2px; border-radius:6px;}
.tp .num{font-variant-numeric:tabular-nums; font-feature-settings:"tnum" 1;}
.tp h1,.tp h2,.tp h3{font-weight:600; letter-spacing:-.015em;}

/* ── каркас ── */
.app{height:100vh; display:flex; flex-direction:column; background:var(--bg); overflow:hidden;}
.demo{display:flex; align-items:center; gap:10px; padding:6px 14px; background:#111C27; color:#9FB0BF; font-size:12px;}
.demo .seg{display:inline-flex; background:rgba(255,255,255,.09); border-radius:7px; padding:2px;}
.demo .seg button{padding:3px 10px; border-radius:5px; font-size:12px; color:#B9C6D2;}
.demo .seg button[data-on="1"]{background:#fff; color:#111C27; font-weight:500;}

.hdr{display:flex; align-items:center; gap:12px; padding:11px 18px; background:#fff; border-bottom:1px solid var(--line);}
.hdr .code{font-size:12.5px; color:var(--ink3); letter-spacing:.02em;}
.hdr h1{font-size:15px;}
.hdr .sp{margin-left:auto; display:flex; gap:7px;}

.cols{flex:1; display:grid; grid-template-columns:1fr 352px; min-height:0;}
@media (max-width:1040px){.cols{grid-template-columns:1fr;} .side{border-left:none; border-top:1px solid var(--line);}}
.main{overflow:auto; display:flex; flex-direction:column; min-width:0;}
.main-in{padding:14px 18px 0; flex:1; max-width:1120px; width:100%;}
.side{overflow:auto; background:#FAFBFC; border-left:1px solid var(--line); padding:12px;}

/* ── общие ── */
.card{background:var(--card); border:1px solid var(--line); border-radius:12px;}
.lbl{font-size:11.5px; color:var(--ink3);}
.name{font-size:13.5px; font-weight:600; letter-spacing:-.01em;}
.chip{display:inline-flex; align-items:center; gap:4px; height:21px; padding:0 8px;
  border-radius:5px; font-size:11.5px; font-weight:500; white-space:nowrap;}
.chip-hot{background:var(--hot-w); color:var(--hot);}
.chip-warm{background:var(--warm-w); color:var(--warm);}
.chip-calm{background:#EEF1F4; color:var(--ink2);}
.chip-ok{background:var(--ok-w); color:var(--ok);}
.chip-blue{background:var(--blue-w); color:var(--blue-d);}
.t-hot{color:var(--hot);} .t-warm{color:var(--warm);} .t-calm{color:var(--ink2);}

.btn{display:inline-flex; align-items:center; justify-content:center; gap:6px; height:33px;
  padding:0 14px; border-radius:8px; font-size:13px; font-weight:500; transition:background .12s; white-space:nowrap;}
.btn-pri{background:var(--blue); color:#fff;} .btn-pri:hover{background:var(--blue-d);}
.btn-ok{background:var(--ok); color:#fff;} .btn-ok:hover{background:#085C38;}
.btn-sec{background:#fff; color:var(--ink); border:1px solid var(--line);}
.btn-sec:hover{background:#F7F9FB;}
.btn-sm{height:28px; padding:0 11px; font-size:12.5px; border-radius:7px;}
.btn:disabled{opacity:.45; cursor:not-allowed;}
.btn-link{color:var(--blue); font-weight:500; padding:0; height:auto;}
.btn-link:hover{text-decoration:underline;}

.pips{display:inline-flex; gap:3px;}
.pips i{width:14px; height:4px; border-radius:2px; background:#DDE3E9; display:block;}
.pips i[data-on="1"]{background:var(--ok);}
.ava{width:20px; height:20px; border-radius:50%; background:#DDE4EB; color:#4A5764;
  font-size:9.5px; font-weight:600; display:inline-flex; align-items:center; justify-content:center; flex:none;}

/* ── строка статуса лота ── */
.status{display:flex; align-items:center; gap:16px; padding:12px 15px;}
.status .cd{font-size:27px; font-weight:600; letter-spacing:-.03em; line-height:1;}
.status .bar{height:3px; border-radius:2px; background:#E6EAEE; overflow:hidden; margin-top:8px; width:100%;}
.status .bar span{display:block; height:100%;}
.stt{display:inline-flex; align-items:center; gap:6px; height:26px; padding:0 10px;
  border-radius:7px; background:#EEF1F4; font-size:12.5px; font-weight:500;}

/* ── вкладки ── */
.tabs{display:flex; align-items:center; gap:2px; margin:12px 0 10px;}
.tabs button{height:31px; padding:0 13px; border-radius:8px; font-size:13px; font-weight:500; color:var(--ink2);}
.tabs button:hover{background:#EAEEF2;}
.tabs button[data-on="1"]{background:#111C27; color:#fff;}
.tabs .hint{margin-left:auto; font-size:12px; color:var(--ink3);}

/* ── содержимое вкладок ── */
.pad{padding:15px;}
.bar-h{display:flex; align-items:center; gap:10px; padding:11px 15px; border-bottom:1px solid var(--line2);}
.doc{border-left:2px solid var(--line); padding:2px 0 2px 15px; margin-top:12px;}
.doc p{font-size:13.5px; line-height:1.65; color:#26333F; max-width:78ch;}
.doc p + p{margin-top:11px;}
.fold-h{display:flex; align-items:center; gap:8px; width:100%; padding:11px 15px; border-top:1px solid var(--line2);}
.empty{padding:26px 15px; text-align:center; color:var(--ink3); font-size:12.5px;}

.spec-wrap{overflow-x:auto;}
table.spec{width:100%; min-width:940px; border-collapse:collapse; table-layout:fixed;}
.spec th{font-size:11.5px; color:var(--ink3); font-weight:400; text-align:left;
  padding:8px 10px; border-bottom:1px solid var(--line);}
.spec td{padding:10px; border-bottom:1px solid var(--line2); vertical-align:top; font-size:12.5px;}
.spec tr:last-child td{border-bottom:none;}
.spec .no{color:var(--ink3); font-size:11.5px;}
.spec .req b{display:block; font-weight:500; line-height:1.5;}
.spec .req b + b{margin-top:3px;}
.orig{font-size:11.5px; color:var(--ink2); line-height:1.55; max-height:176px;
  overflow:auto; padding-right:8px;}
.orig::-webkit-scrollbar{width:5px;}
.orig::-webkit-scrollbar-thumb{background:#DCE2E8; border-radius:3px;}
.cell-in{width:100%; border:1px solid transparent; border-radius:7px; padding:5px 7px; font:inherit;
  font-size:12.5px; background:#FAFBFC; color:var(--ink);}
.cell-in:hover{border-color:var(--line);}
.cell-in::placeholder{color:#B5BFC9;}

.file{display:flex; align-items:center; gap:11px; padding:11px 15px; border-bottom:1px solid var(--line2);}
.ftag{width:32px; height:32px; border-radius:8px; background:#FDECEA; color:#B23A28;
  font-size:9.5px; font-weight:700; display:flex; align-items:center; justify-content:center; flex:none;}

.stats{display:grid; grid-template-columns:repeat(4,1fr); gap:1px; background:var(--line2);}
.stats > div{background:#fff; padding:12px 14px;}
.stats .v{font-size:19px; font-weight:600; letter-spacing:-.02em; margin-top:5px;}
.durs{display:grid; grid-template-columns:repeat(auto-fill,minmax(190px,1fr)); gap:12px 18px; padding:14px 15px;}
.dur .t{height:3px; border-radius:2px; background:#DDE3E9; margin-bottom:6px;}
.dur .t span{display:block; height:100%; border-radius:2px; background:var(--blue);}
.log{display:grid; grid-template-columns:96px 170px 1fr; gap:12px; padding:11px 15px;
  border-top:1px solid var(--line2); font-size:12.5px;}
.log .w{font-weight:500;}

/* ── согласование ── */
.appr{position:sticky; bottom:0; background:#fff; border-top:1px solid var(--line);
  padding:11px 18px; display:flex; align-items:center; gap:14px; flex-wrap:wrap;
  box-shadow:0 -6px 18px rgba(14,22,32,.05); z-index:5;}
.slots{display:flex; gap:6px; flex-wrap:wrap;}
.slot{display:inline-flex; align-items:center; gap:6px; height:28px; padding:0 10px;
  border-radius:8px; border:1px solid var(--line); font-size:12.5px; color:var(--ink2); background:#fff;}
.slot[data-on="1"]{background:var(--ok-w); border-color:#B9DCC9; color:var(--ok);}

/* ── панель: рельса ── */
.side-h{display:flex; align-items:center; justify-content:space-between; gap:8px; padding:2px 3px 9px;}
.rail{padding:2px 0;}
.rail-row{display:grid; grid-template-columns:34px 1fr;}
.rail-gut{position:relative; display:flex; justify-content:center; padding-top:15px;}
.rail-gut:before{content:""; position:absolute; top:0; bottom:0; width:1.5px; background:var(--line);}
.rail-row:first-child .rail-gut:before{top:15px;}
.rail-row:last-child .rail-gut:before{bottom:calc(100% - 15px);}
.mark{position:relative; z-index:1; width:17px; height:17px; border-radius:50%; background:#fff;
  border:1.5px solid #CBD3DB; display:flex; align-items:center; justify-content:center;}
.mark[data-s="done"]{background:var(--ok-w); border-color:#9CCDB6; color:var(--ok);}
.mark[data-s="active"]{border-color:var(--blue); border-width:4px;}
.mark[data-s="hot"]{border-color:var(--hot); border-width:4px;}
.rail-body{padding:11px 12px 12px 2px; border-bottom:1px solid var(--line2);}
.rail-row:last-child .rail-body{border-bottom:none;}
.rail-top{display:flex; align-items:center; gap:8px; justify-content:space-between; min-height:22px; width:100%;}
.rail-sub{font-size:12.5px; color:var(--ink2); margin-top:3px;}
.rail-mine .rail-body{background:#FBFCFE; border-left:2px solid var(--blue); padding-left:9px; margin-left:-9px;}
.quiet .name{color:var(--ink3); font-weight:500;}
.chev{color:var(--ink3); display:inline-flex; transition:transform .15s;}
.chev[data-open="1"]{transform:rotate(90deg);}

.tasks{margin-top:8px; display:flex; flex-direction:column;}
.task{display:grid; grid-template-columns:15px 1fr auto; gap:8px; align-items:center;
  padding:7px 8px 7px 6px; border-radius:8px; width:100%;}
.task:hover{background:#F2F5F8;}
.task-t{font-size:12.5px; font-weight:600; line-height:1.35; overflow:hidden;
  text-overflow:ellipsis; white-space:nowrap;}
.task-m{font-size:11.5px; color:var(--ink3); margin-top:1px;}
.task[data-done="1"] .task-t{color:var(--ink3); font-weight:400;}
.task[data-done="1"] .task-m{color:#A9B4BE;}
.tmark{width:15px; height:15px; display:flex; align-items:center; justify-content:center;
  color:var(--ok); flex:none;}

/* ── карточка задачи ── */
.tv-head{display:flex; align-items:center; gap:8px; padding:10px 12px; border-bottom:1px solid var(--line2);}
.tv-body{padding:14px;}
.tv-title{font-size:16px; line-height:1.3;}
.tv-text{font-size:13px; color:#33414F; line-height:1.6; margin-top:9px; white-space:pre-wrap;}
.meta{margin-top:15px; border-top:1px solid var(--line2);}
.meta div.r{display:flex; align-items:center; justify-content:space-between; gap:12px;
  padding:9px 0; border-bottom:1px solid var(--line2);}
.meta div.r:last-child{border-bottom:none;}
.meta .v{font-size:12.5px; display:inline-flex; align-items:center; gap:6px; text-align:right;}
.res{margin-top:13px; background:var(--ok-w); border-radius:9px; padding:11px 12px;}
.tv-act{display:flex; gap:8px; flex-wrap:wrap; padding:12px 14px; border-top:1px solid var(--line2);}
.hint{font-size:12.5px; color:var(--ink2); padding:11px 14px; border-top:1px solid var(--line2);
  display:flex; gap:7px; align-items:flex-start;}

/* ── модалка ── */
.ov{position:fixed; inset:0; background:rgba(14,22,32,.42); display:flex;
  align-items:center; justify-content:center; padding:18px; z-index:60;}
.mod{background:#fff; border-radius:14px; width:100%; max-width:470px; max-height:92vh;
  overflow:auto; box-shadow:0 18px 48px rgba(14,22,32,.24);}
.mod-h{display:flex; align-items:center; justify-content:space-between; padding:15px 18px 0;}
.mod-h h3{font-size:15.5px;}
.mod-b{padding:14px 18px 4px; display:flex; flex-direction:column; gap:13px;}
.mod-f{display:flex; gap:8px; justify-content:flex-end; padding:14px 18px 16px;}
.field label{display:block; font-size:12px; color:var(--ink2); margin-bottom:5px;}
.inp{width:100%; border:1px solid var(--line); border-radius:9px; padding:8px 11px;
  font:inherit; font-size:13.5px; color:var(--ink); background:#fff;}
.inp::placeholder{color:#A9B4BF;}
textarea.inp{min-height:96px; resize:vertical; line-height:1.55;}
select.inp{height:36px; padding:0 9px;}
.two{display:grid; grid-template-columns:1fr 1fr; gap:11px;}
.x{width:28px; height:28px; border-radius:7px; display:flex; align-items:center; justify-content:center; color:var(--ink3); flex:none;}
.x:hover{background:#F2F5F8; color:var(--ink);}

.kv{display:flex; align-items:center; justify-content:space-between; gap:10px;
  padding:10px 13px; border-bottom:1px solid var(--line2);}
.kv:last-child{border-bottom:none;}
.switch{display:inline-flex; border:1px solid var(--line); border-radius:8px; overflow:hidden;}
.switch button{height:29px; padding:0 12px; font-size:12.5px; color:var(--ink2); background:#fff;}
.switch button[data-on="yes"]{background:var(--ok); color:#fff;}
.switch button[data-on="no"]{background:#5C6B7A; color:#fff;}
`;

/* ─── время ─────────────────────────────────────────────────── */
const T0 = new Date(2026, 8, 8, 11, 44, 0).getTime();
const at = (d, h, m) => new Date(2026, 8, d, h, m, 0).getTime();

const useNow = () => {
  const [n, setN] = useState(T0);
  useEffect(() => {
    const i = setInterval(() => setN((v) => v + 1000), 1000);
    return () => clearInterval(i);
  }, []);
  return n;
};
const left = (ms) => {
  if (ms <= 0) return "просрочена";
  const m = Math.floor(ms / 60000);
  if (m < 60) return `${m} мин`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} ч ${m % 60} мин`;
  return `${Math.floor(h / 24)} д ${h % 24} ч`;
};
const clock = (ms) => {
  if (ms <= 0) return "00:00:00";
  const s = Math.floor(ms / 1000);
  const p = (v) => String(v).padStart(2, "0");
  return `${p(Math.floor(s / 3600))}:${p(Math.floor((s % 3600) / 60))}:${p(s % 60)}`;
};
const lvl = (ms) => (ms < 36e5 ? "hot" : ms < 216e5 ? "warm" : "calm");
const stamp = (t) => {
  const d = new Date(t);
  const p = (v) => String(v).padStart(2, "0");
  return `${p(d.getDate())}.${p(d.getMonth() + 1)}, ${p(d.getHours())}:${p(d.getMinutes())}`;
};
const toLocal = (t) => {
  const d = new Date(t);
  const p = (v) => String(v).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
};
const initials = (s) => s.split(" ").map((w) => w[0]).slice(0, 2).join("");

/* ─── данные ────────────────────────────────────────────────── */
const LOT = {
  code: "GZ000742",
  title: "Приобретение компьютерной техники для садов",
  status: "Новый",
  submit: at(9, 8, 0),
  sign: at(9, 6, 0),
  opened: at(7, 13, 8),
  manager: "Анварбек Нуржауганов",
  spec: "techspec_17569342_43124315.pdf",
};

const NODES = [
  { id: "talk", name: "Обсуждение", kind: "stage", staff: ["Анварбек Нуржауганов", "Айша Тлеубаева"] },
  { id: "review", name: "Разбор", kind: "stage", staff: ["Анварбек Нуржауганов", "Марат Ким"] },
  { id: "legal", name: "Юрист", kind: "dept", staff: ["Айша Тлеубаева", "Данияр Оспанов"] },
  { id: "supply", name: "Снабжение", kind: "dept", staff: ["Марат Ким", "Гульназ Сейтова"] },
  { id: "tech", name: "Технолог", kind: "dept", staff: ["Ерлан Абдиров"] },
];
const DEPTS = NODES.filter((n) => n.kind === "dept");
const STAGES = NODES.filter((n) => n.kind === "stage");
const nd = (id) => NODES.find((n) => n.id === id) || {};
const nodeName = (id) => nd(id).name || id;
/* этап лота — общий, его задачу может взять любой; задача отдела — только этот отдел */
const canWork = (task, role) => nd(task.node).kind === "stage" || role.dept === task.node;

const ROLES = [
  { id: "admin", label: "Менеджер", who: "Анварбек Нуржауганов", dept: null, sign: "Менеджер" },
  { id: "legal", label: "Юрист", who: "Айша Тлеубаева", dept: "legal", sign: "Юрист" },
  { id: "supply", label: "Снабжение", who: "Марат Ким", dept: "supply", sign: "Снабжение" },
];
const SIGNERS = ["Менеджер", "Снабжение", "Юрист", "Технолог", "Сборщик"];

const TASKS0 = [
  {
    id: "t0", node: "review", title: "Заполнить нашу ТС и цены",
    text: "По четырём предметам разбора проставить, что предлагаем и почём. Без этого снабжение не соберёт КП.",
    due: at(8, 16, 0), assignee: "Анварбек Нуржауганов", taken: "Анварбек Нуржауганов", status: "open",
    author: "Анварбек Нуржауганов", created: at(8, 10, 40),
  },
  {
    id: "t01", node: "talk", title: "Отправить замечание заказчику",
    text: "Три замечания по спецификации: марка MacBook Air, процессор M4, требование macOS.",
    due: at(7, 18, 30), assignee: null, taken: "Анварбек Нуржауганов", status: "done",
    author: "Анварбек Нуржауганов", created: at(7, 17, 40),
    closedBy: "Анварбек Нуржауганов", closedAt: at(7, 17, 59),
    result: "Отправлено официальным обращением 07.09 в 17:59. Ждём ответ до конца приёма заявок.",
  },
  {
    id: "t02", node: "talk", title: "Проверить ответ заказчика",
    text: "Как придёт ответ — сверить с исходной спецификацией и решить, идём ли на подачу.",
    due: at(9, 6, 0), assignee: null, taken: null, status: "open",
    author: "Анварбек Нуржауганов", created: at(8, 11, 10),
  },
  {
    id: "t1", node: "legal", title: "Согласовать спецификацию",
    text: "Проверить пункты 4.1–4.6 техспецификации на соответствие п. 412 Правил. Указать, какие требования сужают круг участников и что писать в замечании заказчику.",
    due: at(8, 13, 0), assignee: null, taken: null, status: "open",
    author: "Анварбек Нуржауганов", created: at(8, 10, 36),
  },
  {
    id: "t2", node: "legal", title: "Проверить основания для замечания",
    text: "Подтвердить ссылки на п. 412 Правил и ст. 12 Закона о госзакупках, чтобы обращение приняли.",
    due: at(7, 18, 30), assignee: "Айша Тлеубаева", taken: "Айша Тлеубаева", status: "done",
    author: "Анварбек Нуржауганов", created: at(7, 17, 58),
    closedBy: "Айша Тлеубаева", closedAt: at(7, 17, 59),
    result: "Ссылки верные. Добавила ст. 121 ГК РК по требованию macOS в составе оборудования.",
  },
  {
    id: "t3", node: "supply", title: "Собрать цены поставщиков",
    text: "Три коммерческих предложения на ультрабук и МФУ. По каждому — цена, срок поставки, наличие на складе.",
    due: at(8, 12, 30), assignee: null, taken: null, status: "open",
    author: "Анварбек Нуржауганов", created: at(8, 10, 36),
  },
  {
    id: "t4", node: "supply", title: "Уточнить остатки на складе",
    text: "Проверить, что закрываем 12 позиций из наличия без закупа под заказ.",
    due: at(8, 17, 0), assignee: "Марат Ким", taken: "Марат Ким", status: "open",
    author: "Анварбек Нуржауганов", created: at(8, 11, 6),
  },
];

const SPEC = [
  {
    n: 1, item: "ноутбук: ОС",
    short: ["Ультрабук", "macOS", "MacBook Air"],
    orig: "ҚР СТ 1996-2010 «Компьютерлер. Жалпы сипаттамалар» Түрі: ультрабук. Операциялық жүйе: macOS немесе одан жоғары. Сериясы: MacBook Air. СТ РК 1996-2010 «Компьютеры. Общие технические условия». Тип — ультрабук. Операционная система — не менее macOS. Серия (линейка) MacBook Air.",
  },
  {
    n: 2, item: "ноутбук: экран",
    short: ["≥13,6″, ≥2560×1664, ≥60 Гц", "IPS глянцевое, ≥500 кд/м²", "Без 3D"],
    orig: "Экран диагоналы: кемінде 13,6 дюйм. Экран ажыратымдылығы: кем дегенде 2560x1664. Экранды жаңарту жиілігі: кем дегенде 60 Гц. Экран жарықтығы: кем дегенде 500 cd/m². Экран жабыны: жылтыр. Дисплей түрі: кем дегенде IPS. 3D қолдау: жоқ. Диагональ экрана — не менее 13.6 дюйм, разрешение — не менее 2560x1664, частота обновления — не менее 60 Гц, яркость — не менее 500 кд/м2, покрытие глянцевое, тип матрицы — не менее IPS, поддержка 3D — нет.",
  },
  {
    n: 3, item: "ноутбук: проц",
    short: ["≥ Apple M4", "≥10 ядер", "3200 / 4400 МГц"],
    orig: "Процессордың максималды жиілігі: кем дегенде 4400 МГц. Процессордың моделі: кем дегенде M4. Базалық жиілігі: кем дегенде 3200 МГц. Процессор ядроларының саны: кем дегенде 10. Максимальная частота процессора не менее 4400 МГц, модель процессора не менее M4, базовая частота не менее 3200 МГц, количество ядер не менее 10.",
  },
  {
    n: 4, item: "МФУ",
    short: ["A4, лазерное ч/б, ≥18 стр/мин", "USB ≥2.0, память ≥64 МБ", "Нагрузка ≥8000 стр/мес"],
    orig: "Интерфейсі: кем дегенде 2.0. Пішімі: A4. Басып шығару жылдамдығы: кем дегенде 18 ppm. Басып шығару технологиясы: лазерлік. Түсі: ақ-қара. Картридждер саны: 1 немесе одан көп. Айына беттер саны: кем дегенде 8000. Устройство МФУ, цвет чёрный, уровень шума не более 43 дБ, интерфейс USB не менее 2.0, формат A4, скорость печати не менее 18 стр/мин, технология лазерная, печать чёрно-белая, страниц в месяц не менее 8000, вывод бумаги не менее 150 листов, тип сканера планшетный, память не менее 64 Мб, корпус пластик, вес не более 8,2 кг.",
  },
];

const LOG = [
  { t: at(8, 11, 6), who: "Анварбек Нуржауганов", a: "Взял задачу «Уточнить остатки на складе»", d: "снабжение" },
  { t: at(8, 10, 36), who: "Анварбек Нуржауганов", a: "Завёл задачу отделу «Снабжение»", d: "Собрать цены поставщиков" },
  { t: at(8, 10, 36), who: "Анварбек Нуржауганов", a: "Завёл задачу отделу «Юристы»", d: "Согласовать спецификацию" },
  { t: at(7, 17, 59), who: "Айша Тлеубаева", a: "Закрыла задачу «Обсуждение нужно отправить заказчику»", d: "отправлено" },
  { t: at(7, 17, 58), who: "Анварбек Нуржауганов", a: "Завёл задачу отделу «Юристы»", d: "Обсуждение нужно отправить заказчику" },
  { t: at(7, 14, 38), who: "Анварбек Нуржауганов", a: "Перевёл в «Новый»", d: "администратор" },
  { t: at(7, 14, 38), who: "Анварбек Нуржауганов", a: "Перевёл в «На согласовании»", d: "администратор" },
  { t: at(7, 13, 8), who: "Система", a: "Лот подтянут с портала", d: "goszakup.gov.kz" },
];

const DURS = [
  { s: "Новый", m: 89 }, { s: "Договор", m: 0 }, { s: "Обсуждение", m: 0 },
  { s: "На разборе", m: 0 }, { s: "На согласовании", m: 0 }, { s: "Новый · идёт", m: 1266, live: true },
];

const NOTE = [
  "В технической спецификации указано дополнительное описание пункта плана MacBook Air. Это является указанием конкретной торговой марки и модели оборудования без возможности предложить эквивалент. Данное требование нарушает пункт 412 Правил осуществления государственных закупок и пункт 5 статьи 12 Закона Республики Казахстан «О государственных закупках».",
  "В технической спецификации указано требование поставить ноутбук с процессором модели не менее M4 и видеокартой Apple. Это требование прямо называет конкретный бренд комплектующих и сужает круг участников до одного поставщика.",
  "В технической спецификации ноутбука установлено требование о наличии операционной системы macOS. В данном случае программное обеспечение включено в состав закупаемого оборудования, что нарушает пункт 3 статьи 6 Закона и статью 121 Гражданского кодекса Республики Казахстан.",
];

/* ─── иконки ────────────────────────────────────────────────── */
const Check = ({ s = 10 }) => (
  <svg width={s} height={s} viewBox="0 0 12 12" fill="none" aria-hidden="true">
    <path d="M2.6 6.3 4.8 8.5 9.4 3.7" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
const Chev = ({ s = 11 }) => (
  <svg width={s} height={s} viewBox="0 0 12 12" fill="none" aria-hidden="true">
    <path d="M4.5 2.5 8 6l-3.5 3.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
const Back = () => (
  <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
    <path d="M10 3 5 8l5 5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
const Ex = () => (
  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
    <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
  </svg>
);
const Info = () => (
  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true" style={{ marginTop: 2, flex: "none" }}>
    <circle cx="8" cy="8" r="6.4" stroke="currentColor" strokeWidth="1.3" />
    <path d="M8 7.2v4M8 5.1v.1" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);
const Timer = ({ due, now }) => {
  const d = due - now;
  return <span className={`chip chip-${lvl(d)} num`} title={stamp(due)}>{left(d)}</span>;
};

/* ═══ вкладка: обсуждение ═══════════════════════════════════ */
function TabTalk() {
  const [open, setOpen] = useState(false);
  return (
    <div className="card">
      <div className="bar-h">
        <span className="chip chip-ok">Отправлено</span>
        <span className="lbl num">07.09, 17:59 · ждём ответа заказчика</span>
        <button className="btn btn-link" style={{ marginLeft: "auto" }}>Открыть целиком</button>
      </div>
      <div className="pad">
        <h3 style={{ fontSize: 13.5 }}>Текст замечания</h3>
        <div className="doc">
          {NOTE.map((p, i) => <p key={i}>{p}</p>)}
        </div>
        <p className="lbl" style={{ marginTop: 12 }}>
          Отправленное не правится. Сравнить с исходным можно, когда придёт отказ.
        </p>
      </div>
      <button className="fold-h" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span className="chev" data-open={open ? "1" : "0"}><Chev /></span>
        <span className="name">Требования заказчика</span>
        <span className="lbl">разбор спецификации, чтобы писать замечание не уходя со страницы</span>
        <span className="lbl num" style={{ marginLeft: "auto" }}>11</span>
      </button>
      {open && (
        <div className="pad" style={{ paddingTop: 0 }}>
          {SPEC.map((r) => (
            <div key={r.n} style={{ display: "flex", gap: 10, padding: "8px 0", borderTop: "1px solid var(--line2)" }}>
              <span className="lbl num" style={{ width: 18 }}>{r.n}</span>
              <span style={{ width: 120, fontSize: 12.5 }}>{r.item}</span>
              <span style={{ fontSize: 12.5, color: "var(--ink2)" }}>{r.short.join(" · ")}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ═══ вкладка: разбор ═══════════════════════════════════════ */
function TabSpec({ supplyTaskExists, onSendSupply }) {
  const [our, setOur] = useState({});
  const filled = SPEC.filter((r) => (our[r.n] || "").trim()).length;

  return (
    <div className="card">
      <div className="bar-h">
        <h3 style={{ fontSize: 13.5 }}>Разбор спецификации</h3>
        <button className="btn btn-link num">{LOT.spec}</button>
        <span className="lbl num" style={{ marginLeft: "auto" }}>заполнено {filled} из {SPEC.length}</span>
        <button className="btn btn-sec btn-sm">Разобрать заново</button>
      </div>

      <div className="spec-wrap">
        <table className="spec">
          <thead>
            <tr>
              <th style={{ width: 34 }}>№</th>
              <th style={{ width: 118 }}>Предмет</th>
              <th>Требование заказчика</th>
              <th style={{ width: 190 }}>Кратко</th>
              <th style={{ width: 104 }}>Цена</th>
              <th style={{ width: 186 }}>Наша ТС</th>
            </tr>
          </thead>
          <tbody>
            {SPEC.map((r) => (
              <tr key={r.n}>
                <td className="no num">{r.n}</td>
                <td>{r.item}</td>
                <td><div className="orig">{r.orig}</div></td>
                <td className="req">{r.short.map((s, i) => <b key={i}>{s}</b>)}</td>
                <td>
                  <input className="cell-in num" placeholder="— ₸"
                    value={our[`p${r.n}`] || ""} onChange={(e) => setOur({ ...our, [`p${r.n}`]: e.target.value })} />
                </td>
                <td>
                  <input className="cell-in" placeholder="что предлагаем"
                    value={our[r.n] || ""} onChange={(e) => setOur({ ...our, [r.n]: e.target.value })} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="bar-h" style={{ borderBottom: "none", borderTop: "1px solid var(--line2)" }}>
        <button className="btn btn-sec btn-sm">+ Строка</button>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10 }}>
          {supplyTaskExists && <span className="lbl">Задача снабжению уже стоит — она в очереди отдела.</span>}
          <button className="btn btn-pri" disabled={supplyTaskExists} onClick={onSendSupply}>
            Передать снабжению
          </button>
        </div>
      </div>
    </div>
  );
}

/* ═══ вкладка: файлы ════════════════════════════════════════ */
function TabFiles() {
  return (
    <div className="card">
      <div className="bar-h">
        <h3 style={{ fontSize: 13.5 }}>Файлы</h3>
        <button className="btn btn-sec btn-sm" style={{ marginLeft: "auto" }}>Приложить</button>
      </div>
      <div className="file">
        <span className="ftag">PDF</span>
        <div style={{ minWidth: 0 }}>
          <div className="num" style={{ fontSize: 13, fontWeight: 500 }}>{LOT.spec}</div>
          <div className="lbl">пришёл с портала · по нему собран разбор</div>
        </div>
        <span className="chip chip-calm" style={{ marginLeft: "auto" }}>с портала</span>
        <button className="btn btn-link">Скачать</button>
      </div>
      <div className="empty">
        Своих файлов пока нет. Сюда кладут переписку, счета поставщиков и снимки экрана —<br />
        документы заказчика приходят с портала сами.
      </div>
    </div>
  );
}

/* ═══ вкладка: кто работал ══════════════════════════════════ */
function TabWho({ now }) {
  const maxD = Math.max(...DURS.map((d) => d.m));
  const inWork = now - LOT.opened;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div className="card" style={{ overflow: "hidden" }}>
        <div className="stats">
          <div><div className="lbl">Участвовало людей</div><div className="v num">3</div><div className="lbl">из 2 отделов</div></div>
          <div><div className="lbl">Действий</div><div className="v num">13</div><div className="lbl">13 людьми, 0 автоматических</div></div>
          <div><div className="lbl">Больше всех</div><div className="v" style={{ fontSize: 14 }}>Анварбек Н.</div><div className="lbl">11 действий</div></div>
          <div><div className="lbl">Лот в работе</div><div className="v num">{left(inWork)}</div><div className="lbl num">с {stamp(LOT.opened)}</div></div>
        </div>
      </div>

      <div className="card">
        <div className="bar-h"><h3 style={{ fontSize: 13.5 }}>Сколько держали в статусе</h3></div>
        <div className="durs">
          {DURS.map((d, i) => (
            <div className="dur" key={i}>
              <div className="t"><span style={{ width: `${Math.max(4, (d.m / maxD) * 100)}%`, opacity: d.live ? 1 : 0.45 }} /></div>
              <div style={{ fontSize: 12.5, fontWeight: 500 }}>{d.s}</div>
              <div className="lbl num">{d.m ? left(d.m * 60000) : "0 мин"} · Анварбек Н.</div>
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <div className="bar-h">
          <h3 style={{ fontSize: 13.5 }}>Что делали</h3>
          <span className="lbl" style={{ marginLeft: "auto" }}>по этому считаем премию</span>
        </div>
        {LOG.map((l, i) => (
          <div className="log" key={i}>
            <span className="lbl num">{stamp(l.t)}</span>
            <span className="w">{l.who}</span>
            <span>{l.a}<span className="lbl" style={{ display: "block" }}>{l.d}</span></span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ═══ карточка задачи ═══════════════════════════════════════ */
function TaskView({ task, role, now, onBack, onTake, onClose, onEdit, onReopen }) {
  const [result, setResult] = useState("");
  const isMine = canWork(task, role);
  const stage = nd(task.node).kind === "stage";
  const free = !task.taken && !task.assignee;
  const canDo = isMine && task.status === "open" && (task.taken === role.who || task.assignee === role.who);

  return (
    <div className="card">
      <div className="tv-head">
        <button className="x" onClick={onBack} aria-label="Назад к процессу"><Back /></button>
        <span className="lbl">{nodeName(task.node)}</span>
        <span style={{ marginLeft: "auto" }}>
          {task.status === "done"
            ? <span className="chip chip-ok"><Check s={9} /> Закрыта</span>
            : <Timer due={task.due} now={now} />}
        </span>
      </div>

      <div className="tv-body">
        <h3 className="tv-title">{task.title}</h3>
        <p className="tv-text">{task.text}</p>

        <div className="meta">
          <div className="r"><span className="lbl">Дедлайн</span><span className="v num">{stamp(task.due)}</span></div>
          <div className="r">
            <span className="lbl">Исполнитель</span>
            <span className="v">
              {task.taken || task.assignee
                ? <><span className="ava">{initials(task.taken || task.assignee)}</span>{task.taken || task.assignee}</>
                : <span style={{ color: "var(--ink2)" }}>любой в отделе</span>}
            </span>
          </div>
          <div className="r">
            <span className="lbl">Поставил</span>
            <span className="v num">{task.author.split(" ")[0]} · {stamp(task.created)}</span>
          </div>
          {task.status === "done" && (
            <div className="r">
              <span className="lbl">Закрыл</span>
              <span className="v num">{task.closedBy.split(" ")[0]} · {stamp(task.closedAt)}</span>
            </div>
          )}
        </div>

        {task.status === "done" && task.result && (
          <div className="res">
            <div className="lbl" style={{ color: "var(--ok)" }}>Результат</div>
            <div style={{ fontSize: 12.5, marginTop: 4, lineHeight: 1.55 }}>{task.result}</div>
          </div>
        )}

        {canDo && (
          <div style={{ marginTop: 14 }}>
            <label className="lbl" htmlFor="res" style={{ display: "block", marginBottom: 5 }}>Что сделали</label>
            <textarea id="res" className="inp" style={{ minHeight: 74 }} value={result}
              onChange={(e) => setResult(e.target.value)}
              placeholder="Коротко: к чему пришли. Останется в истории лота." />
          </div>
        )}
      </div>

      {task.status === "open" && isMine && free && (
        <div className="tv-act">
          <button className="btn btn-pri" onClick={() => onTake(task.id)}>Беру на себя</button>
          <span className="lbl" style={{ alignSelf: "center" }}>
            {stage ? "задача на лот — берёт кто угодно" : "задача на весь отдел"}
          </span>
        </div>
      )}
      {canDo && (
        <div className="tv-act">
          <button className="btn btn-ok" disabled={!result.trim()} onClick={() => onClose(task.id, result.trim())}>
            Закрыть задачу
          </button>
          {task.taken && !task.assignee && (
            <button className="btn btn-sec" onClick={() => onTake(task.id, true)}>
              {stage ? "Вернуть в общую очередь" : "Вернуть отделу"}
            </button>
          )}
        </div>
      )}
      {task.status === "open" && isMine && !free && !canDo && (
        <div className="hint"><Info />Задача у {task.taken || task.assignee}. Дождитесь или попросите вернуть в очередь.</div>
      )}
      {role.id === "admin" && (
        <div className="tv-act">
          <button className="btn btn-sec" onClick={() => onEdit(task)}>Изменить</button>
          {task.status === "done" && <button className="btn btn-sec" onClick={() => onReopen(task.id)}>Вернуть в работу</button>}
        </div>
      )}
      {!isMine && role.id !== "admin" && (
        <div className="hint"><Info />Задача другого отдела — только для просмотра.</div>
      )}
    </div>
  );
}

/* ═══ модалка ═══════════════════════════════════════════════ */
function TaskModal({ initial, defaultNode, onSave, onCancel }) {
  const edit = Boolean(initial);
  const [node, setNode] = useState(initial?.node || defaultNode || "legal");
  const [title, setTitle] = useState(initial?.title || "");
  const [text, setText] = useState(initial?.text || "");
  const [due, setDue] = useState(toLocal(initial?.due || T0 + 3 * 36e5));
  const [who, setWho] = useState(initial?.assignee || "");
  const first = useRef(null);

  useEffect(() => {
    first.current?.focus();
    const k = (e) => e.key === "Escape" && onCancel();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onCancel]);

  const staff = nd(node).staff || [];
  const ok = title.trim() && due;

  return (
    <div className="ov" onMouseDown={(e) => e.target === e.currentTarget && onCancel()}>
      <div className="mod" role="dialog" aria-modal="true" aria-label={edit ? "Изменить задачу" : "Новая задача"}>
        <div className="mod-h">
          <h3>{edit ? "Изменить задачу" : "Новая задача"}</h3>
          <button className="x" onClick={onCancel} aria-label="Закрыть"><Ex /></button>
        </div>
        <div className="mod-b">
          <div className="field">
            <label htmlFor="m-title">Что сделать</label>
            <input id="m-title" ref={first} className="inp" value={title}
              onChange={(e) => setTitle(e.target.value)} placeholder="Согласовать спецификацию" />
          </div>
          <div className="field">
            <label htmlFor="m-text">Описание</label>
            <textarea id="m-text" className="inp" value={text} onChange={(e) => setText(e.target.value)}
              placeholder="Что именно проверить, на что смотреть, что вернуть в ответе." />
          </div>
          <div className="two">
            <div className="field">
              <label htmlFor="m-node">Куда</label>
              <select id="m-node" className="inp" value={node} onChange={(e) => { setNode(e.target.value); setWho(""); }}>
                <optgroup label="Этапы лота">
                  {STAGES.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
                </optgroup>
                <optgroup label="Отделы">
                  {DEPTS.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
                </optgroup>
              </select>
            </div>
            <div className="field">
              <label htmlFor="m-due">Дедлайн</label>
              <input id="m-due" type="datetime-local" className="inp num" value={due} onChange={(e) => setDue(e.target.value)} />
            </div>
          </div>
          <div className="field">
            <label htmlFor="m-who">Исполнитель</label>
            <select id="m-who" className="inp" value={who} onChange={(e) => setWho(e.target.value)}>
              <option value="">{nd(node).kind === "stage" ? "Любой — кто возьмёт" : "Любой в отделе — кто возьмёт"}</option>
              {staff.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
        </div>
        <div className="mod-f">
          <button className="btn btn-sec" onClick={onCancel}>Отмена</button>
          <button className="btn btn-pri" disabled={!ok}
            onClick={() => onSave({
              id: initial?.id, node, title: title.trim(), text: text.trim(),
              due: new Date(due).getTime(), assignee: who || null,
            })}>
            {edit ? "Сохранить" : "Поставить задачу"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ═══ строка отдела ═════════════════════════════════════════ */
function NodeRow({ node, tasks, role, now, open, onToggle, onOpenTask, onAdd, base, meta, idle }) {
  const act = tasks.filter((t) => t.status === "open");
  const done = tasks.filter((t) => t.status === "done");
  const stage = node.kind === "stage";
  const mine = role.dept === node.id;
  const nearest = act.length ? Math.min(...act.map((t) => t.due)) : null;
  const state = act.length
    ? (nearest - now < 36e5 ? "hot" : base || "active")
    : tasks.length ? (base === "active" ? "active" : "done") : base || "idle";
  const list = [...act.sort((a, b) => a.due - b.due), ...done.sort((a, b) => b.closedAt - a.closedAt)];

  return (
    <div className={`rail-row ${mine ? "rail-mine" : ""}`}>
      <div className="rail-gut"><span className="mark" data-s={state}>{state === "done" && <Check />}</span></div>
      <div className={`rail-body ${tasks.length === 0 && !meta ? "quiet" : ""}`}>
        <button className="rail-top" onClick={onToggle} aria-expanded={open}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6, minWidth: 0 }}>
            <span className="chev" data-open={open ? "1" : "0"}><Chev /></span>
            <span className="name">{node.name}</span>
          </span>
          {act.length > 0
            ? <Timer due={nearest} now={now} />
            : idle || <span className="lbl">{tasks.length ? "все задачи закрыты" : "задач нет"}</span>}
        </button>

        <div className="rail-sub" style={{ paddingLeft: 17 }}>
          {meta}
          {tasks.length > 0 && (
            <div className="num" style={{ marginTop: meta ? 2 : 0 }}>
              {act.length} открыто · {done.length} закрыто
              {(mine || stage) && act.some((t) => !t.taken && !t.assignee) && (
                <span className="chip chip-blue" style={{ marginLeft: 7 }}>есть свободная</span>
              )}
            </div>
          )}
        </div>

        {open && (
          <>
            {list.length > 0 && (
              <div className="tasks">
                {list.map((t) => {
                  const d = t.status === "done";
                  return (
                    <button className="task" key={t.id} data-done={d ? "1" : "0"} onClick={() => onOpenTask(t.id)}>
                      <span className="tmark">{d && <Check s={11} />}</span>
                      <span style={{ minWidth: 0 }}>
                        <span className="task-t" style={{ display: "block" }}>{t.title}</span>
                        <span className="task-m num">
                          {d
                            ? `${t.closedBy.split(" ")[0]} · ${stamp(t.closedAt)}`
                            : t.taken || t.assignee ? (t.taken || t.assignee).split(" ")[0] : "свободна"}
                        </span>
                      </span>
                      {!d && (
                        <span className={`num t-${lvl(t.due - now)}`} style={{ fontSize: 11.5, fontWeight: 500 }}>
                          {left(t.due - now)}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
            {role.id === "admin" && (
              <button className="btn btn-link btn-sm" style={{ marginTop: 6, marginLeft: 6 }} onClick={onAdd}>
                + Задача {stage ? "на этап" : "отделу"}
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}

/* ═══ правая панель ═════════════════════════════════════════ */
function Side({ role, now, tasks, signs, openId, setOpenId, onNew, onEdit, take, closeTask, reopen }) {
  const [openDepts, setOpenDepts] = useState({});
  const [join, setJoin] = useState(null);
  const toggle = (id) => setOpenDepts((s) => ({ ...s, [id]: !s[id] }));

  const src = role.dept ? tasks.filter((t) => t.node === role.dept || nd(t.node).kind === "stage") : tasks;
  const stats = { open: src.filter((t) => t.status === "open").length, done: src.filter((t) => t.status === "done").length };
  const task = tasks.find((t) => t.id === openId);

  if (task)
    return (
      <TaskView
        task={task} role={role} now={now} onBack={() => setOpenId(null)}
        onTake={take} onClose={(id, r) => { closeTask(id, r); setOpenId(null); }}
        onEdit={onEdit} onReopen={reopen}
      />
    );

  return (
    <>
      <div className="side-h">
        <span className="num" style={{ fontSize: 12.5, color: "var(--ink2)" }}>
          {role.dept ? "Ваши задачи" : "Задачи"}: <b style={{ color: "var(--ink)" }}>{stats.open}</b> открыто · {stats.done} закрыто
        </span>
        {role.id === "admin" && <button className="btn btn-sec btn-sm" onClick={() => onNew("review")}>Новая задача</button>}
      </div>

      <div className="card rail">
        {NODES.map((n) => (
          <NodeRow
            key={n.id} node={n} role={role} now={now}
            tasks={tasks.filter((t) => t.node === n.id)}
            open={!!openDepts[n.id]} onToggle={() => toggle(n.id)}
            onOpenTask={setOpenId} onAdd={() => onNew(n.id)}
            base={n.id === "talk" ? "done" : n.id === "review" ? "active" : null}
            idle={n.id === "talk" ? <span className="chip chip-ok">Отправлено</span>
              : n.id === "review" ? <Timer due={LOT.submit} now={now} /> : null}
            meta={n.id === "talk" ? <span className="num">07.09, 17:59 · ждём ответа заказчика</span>
              : n.id === "review" ? (
                <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                  <span className="ava">{initials(LOT.manager)}</span>Ведёт Анварбек Н.
                </span>
              ) : null}
          />
        ))}

        <div className="rail-row">
          <div className="rail-gut">
            <span className="mark" data-s={signs.length === SIGNERS.length ? "done" : "idle"}>
              {signs.length === SIGNERS.length && <Check />}
            </span>
          </div>
          <div className={`rail-body ${signs.length ? "" : "quiet"}`}>
            <div className="rail-top">
              <span className="name">Подача</span>
              <span className="lbl num">подписи до {stamp(LOT.sign)}</span>
            </div>
            <div className="rail-sub" style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span className="pips">
                {SIGNERS.map((s) => <i key={s} data-on={signs.includes(s) ? "1" : "0"} />)}
              </span>
              <span className="num">{signs.length} из {SIGNERS.length}</span>
            </div>
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 10 }}>
        <div className="kv">
          <span className="lbl">Ведёт лот</span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 7, fontSize: 13 }}>
            <span className="ava">{initials(LOT.manager)}</span>Анварбек Н.
          </span>
        </div>
        {role.id === "admin" && (
          <div className="kv">
            <span className="lbl">Участвуем?</span>
            <span className="switch">
              <button data-on={join === "yes" ? "yes" : ""} onClick={() => setJoin("yes")}>Да</button>
              <button data-on={join === "no" ? "no" : ""} onClick={() => setJoin("no")}>Нет</button>
            </span>
          </div>
        )}
      </div>
    </>
  );
}

/* ═══ экран ═════════════════════════════════════════════════ */
export default function TenderWorkspace() {
  const now = useNow();
  const [r, setR] = useState("admin");
  const role = ROLES.find((x) => x.id === r);
  const [tab, setTab] = useState("talk");
  const [tasks, setTasks] = useState(TASKS0);
  const [openId, setOpenId] = useState(null);
  const [modal, setModal] = useState(null);
  const [signs, setSigns] = useState([]);

  const take = (id, back) => setTasks((ts) => ts.map((t) => (t.id === id ? { ...t, taken: back ? null : role.who } : t)));
  const closeTask = (id, result) =>
    setTasks((ts) => ts.map((t) => (t.id === id ? { ...t, status: "done", result, closedBy: role.who, closedAt: now } : t)));
  const reopen = (id) =>
    setTasks((ts) => ts.map((t) => (t.id === id ? { ...t, status: "open", result: null, closedBy: null, closedAt: null } : t)));
  const save = (data) => {
    setTasks((ts) => data.id
      ? ts.map((t) => (t.id === data.id ? { ...t, ...data } : t))
      : [...ts, { ...data, id: `t${Date.now()}`, taken: null, status: "open", author: role.who, created: now }]);
    setModal(null);
  };

  const d = LOT.submit - now;
  const pct = Math.min(100, Math.max(2, ((now - LOT.opened) / (LOT.submit - LOT.opened)) * 100));
  const supplyOpen = tasks.some((t) => t.node === "supply" && t.status === "open");
  const signed = signs.includes(role.sign);

  const TABS = [
    { id: "talk", n: "Обсуждение", h: "официальное обращение к заказчику до подачи заявки" },
    { id: "spec", n: "Разбор", h: "спецификация заказчика, разложенная по предметам" },
    { id: "files", n: "Файлы", h: "спецификация заказчика и то, что приложили мы" },
    { id: "who", n: "Кто работал", h: "кто что делал — по этому считаем премию" },
  ];

  return (
    <div className="tp">
      <style>{CSS}</style>
      <div className="app">
        <div className="demo">
          <span>Демо · вы вошли как</span>
          <span className="seg">
            {ROLES.map((x) => (
              <button key={x.id} data-on={r === x.id ? "1" : "0"} onClick={() => { setR(x.id); setOpenId(null); }}>{x.label}</button>
            ))}
          </span>
          <span style={{ marginLeft: "auto" }}>{role.who}</span>
        </div>

        <div className="hdr">
          <span className="code num">{LOT.code}</span>
          <h1>{LOT.title}</h1>
          <span className="sp">
            <button className="btn btn-sec btn-sm">Данные закупки</button>
            <button className="btn btn-sec btn-sm">На площадке</button>
            <button className="btn btn-sec btn-sm">Ко всем лотам</button>
          </span>
        </div>

        <div className="cols">
          <div className="main">
            <div className="main-in">
              <div className="card status">
                <span className="stt"><span style={{ width: 7, height: 7, borderRadius: 4, background: "#5C6B7A" }} />{LOT.status}</span>
                <div style={{ minWidth: 190 }}>
                  <div className="lbl">До конца приёма заявок</div>
                  <div className={`cd num t-${lvl(d)}`} style={{ marginTop: 4 }}>{clock(d)}</div>
                </div>
                <div style={{ flex: 1, minWidth: 120 }}>
                  <div className="lbl num">приём до {stamp(LOT.submit)} · подписи до {stamp(LOT.sign)}</div>
                  <div className="bar">
                    <span style={{ width: `${pct}%`, background: lvl(d) === "hot" ? "var(--hot)" : lvl(d) === "warm" ? "#D08A2C" : "var(--ink)" }} />
                  </div>
                </div>
                <button className="btn btn-sec btn-sm">Изменить статус</button>
              </div>

              <div className="tabs">
                {TABS.map((t) => (
                  <button key={t.id} data-on={tab === t.id ? "1" : "0"} onClick={() => setTab(t.id)}>{t.n}</button>
                ))}
                <span className="hint">{TABS.find((t) => t.id === tab).h}</span>
              </div>

              {tab === "talk" && <TabTalk />}
              {tab === "spec" && <TabSpec supplyTaskExists={supplyOpen} onSendSupply={() => setModal({ node: "supply" })} />}
              {tab === "files" && <TabFiles />}
              {tab === "who" && <TabWho now={now} />}
              <div style={{ height: 16 }} />
            </div>

            <div className="appr">
              <div>
                <div className="name">Готов к участию</div>
                <div className="lbl num">{signs.length} из {SIGNERS.length} подписей · без пяти статус недоступен</div>
              </div>
              <div className="slots">
                {SIGNERS.map((s) => (
                  <span className="slot" key={s} data-on={signs.includes(s) ? "1" : "0"}>
                    {signs.includes(s) && <Check s={9} />}{s}
                  </span>
                ))}
              </div>
              <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
                <button className="btn btn-sec">Отклонить</button>
                <button
                  className="btn btn-pri" disabled={signed}
                  onClick={() => setSigns((s) => [...s, role.sign])}
                >
                  {signed ? `Подписано за «${role.sign}»` : `Подписать за «${role.sign}»`}
                </button>
              </div>
            </div>
          </div>

          <div className="side">
            <Side
              role={role} now={now} tasks={tasks} signs={signs}
              openId={openId} setOpenId={setOpenId}
              onNew={(node) => setModal({ node })} onEdit={(t) => setModal({ task: t })}
              take={take} closeTask={closeTask} reopen={reopen}
            />
          </div>
        </div>

        {modal && (
          <TaskModal initial={modal.task} defaultNode={modal.node} onSave={save} onCancel={() => setModal(null)} />
        )}
      </div>
    </div>
  );
}