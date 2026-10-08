# -*- coding: utf-8 -*-
"""
анализ_v10.14.py
Фикс классификации контента:
- news / incident / social_story / help_request / opinion / advertising / nonlocal
- просьбы найти дом, сборы, помощь животным и людям не попадают
  в "ВИРУСНЫЙ СИГНАЛ" новостной очереди
"""

import json, re, sys
from pathlib import Path

# Prefer UTF-8; if the host console is legacy, console_print below falls back safely.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass


def console_print(message):
    """Print without allowing a legacy Windows console to crash the process."""
    text = str(message)
    try:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        text.encode(encoding)
        print(text, flush=True)
    except (UnicodeEncodeError, LookupError):
        print(text.encode("ascii", "backslashreplace").decode("ascii"), flush=True)
from datetime import datetime

from metrics import aggregate_topic_stats, topic_age_hours

INPUT=Path("vk_today.json")
OUTPUT=Path("editor_queue.json")

OFFICIAL_POS=[
 r"\bпрокуратур\w*\s+(?:сообщил|заявил|выявил|проверил|установил|внёс|вынес|потребовал)",
 r"\bпо данным прокуратур\w*", r"\bследственн\w+\s+комитет\w*\s+(?:сообщил|начал|возбудил|проводит|расследует)",
 r"\bск\s+(?:сообщил|начал|возбудил|проводит|расследует)", r"\bмчс\s+(?:сообщил|предупредил|рассказал)",
 r"\bгибдд\s+(?:сообщил|предупредил|рассказал)", r"\bсуд\s+(?:вынес|назначил|арестовал|приговорил|рассмотрел)",
 r"\bадминистраци\w*\s+(?:сообщил|рассказал|объявил|предупредил)",
 r"\bправительств\w+\s+омск\w*\s+(?:сообщил|объявил|утвердил|принял)",
 r"\bофициально\s+(?:сообщил|подтвердил|заявил)",
 r"\b(?:приказ|распоряжени\w*)\s+(?:подписал|подписано|утвержд\w*)",
 r"\b(?:мэрия|администраци\w*|департамент\w*)\s+(?:сообщил|заявил|подтвердил|объявил|сообщает)",
 r"\b(?:директор|руководител\w*)\s+(?:департамент\w*|администраци\w*)\s+(?:подписал|утвердил)",
 r"\bсоответствующ\w+\s+(?:приказ|распоряжени\w*)",
 r"\bпо данным следств\w*",
 r"\bпо данным ск\b",
 r"\bпо данным полиции\b",
 r"\bпо данным мвд\b",
 r"\bпо данным угмс\b",
 r"\bпо данным ведомств\w*",
 r"\bследств\w*\s+(?:установил|сообщил|выясняет|расследует)",
 r"\bобь-иртышск\w+\s+угмс",
 r"\bугмс\b"
]
OFFICIAL_NEG=[r"официальн\w*\s+информаци\w*\s+(?:пока\s+)?(?:нет|не\s+поступ)",
              r"официальн\w*\s+информаци\w*\s+не\s+(?:подтвержден|поступил)",
              r"официальн\w*\s+подтверждени\w*\s+нет",
              r"официальн\w*\s+информаци\w*.*?пока\s+не\s+поступ"]
REGIONAL=["om1","om1.ru","ngs55","superomsk","kvnews","омскинформ","omskinform",
 "lenta novostey","лента новостей омск","gtrk irtysh","гтрк иртыш","novy omsk",
 "новый омск","aif omsk","аиф омск","omskregion.info","sibir041","omsk55","омсми"]
NONLOCAL=["иркутской области","иркутск","краснодарского края","краснодар","бурятии","бурятия",
 "москва","москве","санкт-петербург","екатеринбург","тюмени","тюменской области",
 "новосибирске","новосибирской области","красноярске","красноярского края"]
OMSK=["омск","омской области","омская область","омском","омские","омский","тара","калачинск","исилькуль"]

AD=["реклама","скидк","акция","акции","акцию","оформить","подать заявку","бесплатная консультация","utm_",
 "app5898182","спишем долги","списание долгов"]
OPINION=["наш любимый омск","бравурных репортажей","можете задонатить","по большому секрету",
 "прорывная команда","клоунада","позор","авангардный рывок","только вот незадача",
 "пропиаренных","какие плюшки","омичей травят","а где эти","ну и да, если кто",
 "давайте подумаем","разве можно так относиться","куда смотрят инспекторы"]
HELP=["просьба о помощи","к кому обращаться","что нам делать","может кто видел","может кто-нибудь видел",
 "хотел бы найти владельца","хотел найти владельца","нужны записи","есть записи с видео регистратора",
 "есть записи с видеорегистратора","записи с видео регистратора","опубликуйте, пожалуйста", "опубликуйте пожалуйста", "уважаемые автолюбители", "огромная просьба", "пожалуйста, напишите", "пожалуйста напишите", "прошу найти", "просим найти", "нужны записи", "записи видеорегистратора", "если у кого-то есть запись", "если у кого есть запись", "ищем очевидцев", "найти очевидцев", "поиск очевидцев", "просьба откликнуться", "опубликуйте, пожалуйста", "ищет дом","ищет хозяина","ищет хозяев","нужен дом","нужен хозяин","нужны хозяева",
 "заберите домой","готовы забрать","опубликуйте, пожалуйста","огромная просьба","нужны записи",
 "записи видеорегистратора","если у кого-то есть запись","ищем очевидцев","просьба откликнуться","возьмите домой","приют","передержк","нужна помощь",
 "нужна финансовая помощь","сбор средств","собрать деньги","помочь животн","помочь собак",
 "помочь кошк","сделайте репост","репост — шанс","репост это шанс"]
COMPLAINT=["жители жалуются","жители пожаловались","омичи жалуются","омичи пожаловались",
 "жалоба жителей","сообщают жители","по словам жителей","очевидцы сообщают",
 "вопрос к гаи","куда смотрят инспекторы","сколько это будет продолжаться",
 "почему нет","почему отключили","не работает","не убирают","не убрали",
 "льётся вода","течёт вода","нет отопления","нет горячей воды","нет газа",
 "дети мёрзнут","всё перекопали","разве можно так относиться"]

NEWS=["произош","произошла","произошло","сообщил","сообщили","задержан","задержали",
 "возбуждено уголовное дело","уголовное дело","погиб","погибла","погибли","умер","умерла",
 "пожар","загорелся","авари","дтп","столкнул","суд","приговор","арестовал","взрыв",
 "выброс","превысил норм","тариф","отключ","закрыли","открыли","введут","изменят",
 "проверка","прокуратура","следственный комитет","мчс","гибдд","администрация"]

def norm(x): return re.sub(r"\s+"," ",str(x).lower()).strip()
def text_of(p):
    for k in ("text","description","content","post_text","message"):
        if p.get(k): return str(p[k])
    return ""
def source_of(p):
    for k in ("source","group","group_name","community","author","from"):
        if p.get(k): return str(p[k])
    return ""
def has(t,a): return any(x in norm(t) for x in a)
def rx(t,a): return any(re.search(x,t,re.I) for x in a)

# Editorial hard stop-list for topics outside the current editorial goal.
EXCLUDED_TOPIC_PATTERNS = [
    "бпла", "беспилот", "дрон", "дроны", "дрона", "дронами",
    "воздушн", "тревог", "ракетн", "опасност", "пво"
]

def excluded_topic(t):
    return has(t, EXCLUDED_TOPIC_PATTERNS)

def promotional_ad(t):
    if has(t, AD):
        return True
    channel_words = ["канал", "канала", "каналов"]
    promo_words = [
        "подписывайтесь", "подпишитесь", "подписывайся",
        "наши каналы", "самые свежие новости",
        "где публикуются самые свежие", "публикуем в нашем канале",
        "актуальную информацию", "в режиме онлайн",
        "следим за обстановкой", "ищите по запросу",
        "вся оперативная информация"
    ]
    direct_promo = [
        "публикуем в нашем канале", "актуальную информацию",
        "в режиме онлайн", "следим за обстановкой",
        "ищите по запросу", "вся оперативная информация"
    ]
    return has(t, channel_words) and has(t, promo_words) or has(t, direct_promo)


def classify(p):
    t=norm(text_of(p)); s=norm(source_of(p))
    official=not rx(t,OFFICIAL_NEG) and (
        rx(t,OFFICIAL_POS)
        or bool(re.search(r"\bобь-иртышск\w*\s+угмс\b", t))
        or bool(re.search(r"\bугмс\b", t))
    )
    media=any(x in s or x in t for x in REGIONAL)
    official_source_name = bool(re.search(
        r"\b(обь-иртышск\w*\s+угмс|угмс|прокуратур\w*|следственн\w*\s+комитет|мчс|гибдд|мвд|полици\w*)\b",
        t, re.I
    ))
    # Если прямо сказано, что официального подтверждения нет,
    # название ведомства само по себе не делает сообщение официальным.
    if rx(t, OFFICIAL_NEG):
        official = False
    else:
        official = official or official_source_name

    nonlocal_hit=has(t,NONLOCAL); omsk_hit=has(t,OMSK)
    explicit_omsk=omsk_hit and nonlocal_hit
    excluded=excluded_topic(t)
    ad=promotional_ad(t); opinion=has(t,OPINION)
    help_req_raw=has(t,HELP) or bool(re.search(r"(?:опубликуйте|огромная просьба|просьба о помощи|к кому обращаться|что нам делать|может кто(?:-нибудь)? видел|пожалуйста.{0,25}(?:запис|напиш|отклик)|просим|прошу|хотел(?: бы)? найти).{0,160}(?:очевидц|видеорегистратор|запис|помощь|владельц)", t, re.I))
    # Просьба о помощи внутри уже состоявшегося события не превращает
    # саму новость в "не новость". Например: "пропал человек, нужны записи".
    event_in_help = has(t, ["пропал","пропала","пропали","разыскива","погиб","погибла","погибли","умер","пожар","дтп","авари","столкнул","задержан","возбуждено уголовное дело"])
    help_req = help_req_raw and not event_in_help
    # Просьба о помощи/поиске свидетелей не становится официальной новостью
    # только из-за упоминания ГИБДД, полиции, МЧС и т.п.
    if help_req:
        official = False
    # Риторические/оценочные публикации: не считаем их новостями только из-за цифр или названий ведомств.
    opinion = opinion or bool(re.search(r"(?:\?|!!!).*(?:где|почему|зачем|какие|сколько|разве|куда)", t, re.I))
    complaint=has(t,COMPLAINT)
    news_signal=has(t,NEWS)

    if excluded: typ="excluded_topic"
    elif ad: typ="advertising"
    elif opinion: typ="opinion"
    elif help_req: typ="help_request"
    elif nonlocal_hit and not explicit_omsk: typ="nonlocal"
    elif official: typ="news"
    elif media and news_signal: typ="news"
    elif complaint and not official: typ="complaint"
    elif news_signal: typ="news"
    else: typ="social_story"

    if excluded or ad or opinion or help_req: conf=0
    elif official: conf=90
    elif media: conf=65
    elif complaint: conf=10
    else: conf=25
    if nonlocal_hit and not explicit_omsk: conf=min(conf,10)

    return {
      "content_type":typ,"source_type":("official_attribution" if official else
        "regional_media" if media else "complaint" if complaint else "social"),
      "official_attribution":official,"complaint_signal":complaint,
      "help_request":help_req,"opinion_signal":opinion,"advertising_signal":ad,"excluded_topic":excluded,
      "nonlocal_detected":nonlocal_hit and not explicit_omsk,
      "explicit_omsk_relevance":explicit_omsk,"confidence":conf
    }

def words(s): return set(re.findall(r"[а-яёa-z0-9]{4,}",norm(s)))
def similar(a,b):
    A,B=words(a),words(b)
    if not A or not B:return False
    j=len(A&B)/len(A|B)
    nums=set(re.findall(r"\b\d+(?:[.,]\d+)?\b",norm(a)))&set(re.findall(r"\b\d+(?:[.,]\d+)?\b",norm(b)))
    anchors=sum(x in norm(a) and x in norm(b) for x in
      ["прокуратур","мчс","гибдд","суд","погиб","умер","пожар","авари","выброс","тариф","мошен",
 "школ","столов","возгора","теплотрас","кипят"])
    na, nb = norm(a), norm(b)
    # Специальное объединение допустимо только для явно совпадающего
    # школьного пожара; общие слова "теплотрасса/выбросы/тарифы"
    # сами по себе не означают один и тот же инфоповод.
    same_event = (
        ("школ" in na and "школ" in nb) and
        any(x in na for x in ["пожар", "горел", "возгора"]) and
        any(x in nb for x in ["пожар", "горел", "возгора"]) and
        bool(set(re.findall(r"\b(?:№\s*)?\d+\b", na)) &
             set(re.findall(r"\b(?:№\s*)?\d+\b", nb)))
    )

    # Сильная сигнатура одного конкретного происшествия.
    # Нужны минимум 3 характерных признака, чтобы не склеивать
    # разные жалобы про теплотрассы/выбросы/кипяток.
    event_signatures = [
        ["рабоч", "теплов", "кипят", "ожог", "уголовн", "гибел", "гагарин"],
    ]
    strong_event = any(
        sum(x in na and x in nb for x in sig) >= 3
        for sig in event_signatures
    )
    return j>=.23 or (anchors>=2 and j>=.12) or (len(nums)>=2 and j>=.12) or same_event or strong_event

def main():
    with INPUT.open(encoding="utf-8") as f:d=json.load(f)
    posts=d if isinstance(d,list) else next((d[k] for k in ("posts","items","data") if isinstance(d.get(k),list)),[])
    topics=[]
    for p in posts:
        t=text_of(p)
        for q in topics:
            if any(similar(t,m["text"]) for m in q["members"]):
                q["members"].append({"text":t,"post":p});break
        else:topics.append({"members":[{"text":t,"post":p}]})

    out=[]
    for q in topics:
        ms=q["members"]; infos=[classify(m["post"]) for m in ms]
        texts=[m["text"] for m in ms]; sources={source_of(m["post"]) for m in ms if source_of(m["post"])}
        conf=round(sum(i["confidence"] for i in infos)/len(infos),1)
        official=any(i["official_attribution"] for i in infos)
        nonlocal_only=all(i["nonlocal_detected"] for i in infos)
        help_only=all(i["help_request"] for i in infos)
        opinion_only=all(i["opinion_signal"] for i in infos)
        ad_only=all(i["advertising_signal"] for i in infos)
        excluded_only=all(i.get("excluded_topic",False) for i in infos)
        complaint_only=all(i["complaint_signal"] and not i["official_attribution"] for i in infos)

        # Приоритет типа: помощь -> жалоба -> мнение.
        # Жалоба может содержать эмоциональные/оценочные фразы, но это
        # не превращает её автоматически в "мнение".
        content=infos[0]["content_type"]
        if help_only: content="help_request"
        elif complaint_only: content="complaint"
        elif opinion_only: content="opinion"
        elif ad_only: content="advertising"
        elif nonlocal_only: content="nonlocal"

        # Shared aggregation keeps analysis and predictor statistically consistent.
        views, reposts, likes, comments = aggregate_topic_stats(ms)
        hours_old = topic_age_hours(ms, datetime.now().timestamp())

        engagement = min(100, ((likes + comments * 2 + reposts * 4) / max(views, 1)) * 1000)
        velocity = min(100, (views / hours_old) / 250 * 100)
        discussion = min(100, (comments / max(views, 1)) * 2500)
        spread = min(100, (reposts / max(views, 1)) * 5000)

        hook = 0
        hook += 18 if any(x in " ".join(texts).lower() for x in ["снесут", "запрет", "пропал", "погиб", "задержали", "авар", "пожар", "дтп"]) else 0
        hook += 12 if any(x in " ".join(texts).lower() for x in ["почему", "как так", "куда смотр", "что будет", "впервые", "необыч"]) else 0
        hook += 10 if any(x in " ".join(texts).lower() for x in ["омск", "омской", "омич", "омичи"]) else 0

        # Малый охват не обнуляет ранний сигнал.
        early_signal = min(100, velocity * 0.45 + engagement * 0.25 + discussion * 0.15 + spread * 0.15)
        viral = round(min(100, early_signal * 0.65 + hook * 0.35), 1)
        locality=0 if nonlocal_only else 100 if any("омск" in norm(t) for t in texts) else 30
        editorial=locality*.45+viral*.25+conf*.30
        score=round(viral*.5+editorial*.5,1)

        complaint_viral_signal = (
            complaint_only and
            (viral >= 60 or views >= 5000 or reposts >= 10 or len(ms) >= 3)
        )

        # Порядок принципиален:
        # 1) реклама — отбрасываем;
        # 2) помощь — никогда не считаем новостью;
        # 3) жалоба — либо наблюдаем, либо показываем как непроверенный
        #    вирусный сигнал;
        # 4) обычное мнение — отбрасываем.
        if excluded_only:
            status,action="reject","ОТБРОСИТЬ: ИСКЛЮЧЁННАЯ ТЕМА"
        elif ad_only:
            status,action="reject","ОТБРОСИТЬ: РЕКЛАМА"
        elif help_only:
            status,action="watch","НЕ НОВОСТЬ: ПОМОЩЬ"
        elif complaint_viral_signal:
            status,action="unconfirmed_signals","ВИРУСНЫЙ СИГНАЛ: ЖАЛОБА"
        elif complaint_only:
            status,action="watch","НАБЛЮДАТЬ: ЖАЛОБА"
        elif opinion_only:
            status,action="reject","ОТБРОСИТЬ: МНЕНИЕ"
        elif nonlocal_only:
            status,action="watch","НАБЛЮДАТЬ: НЕ ОМСК"
        elif official:
            status,action=("take_now","БРАТЬ") if score>=62 else ("check","БЫСТРО ПРОВЕРИТЬ")
        elif conf<=25 and viral>=60:
            status,action="unconfirmed_signals","ВИРУСНЫЙ СИГНАЛ"
        else:
            status="take_now" if score>=68 else "check" if score>=55 else "watch"
            action={"take_now":"БРАТЬ","check":"ПРОВЕРИТЬ","watch":"НАБЛЮДАТЬ"}[status]

        primary_post = ms[0]["post"] if ms else {}
        primary_url = primary_post.get("url") or primary_post.get("post_url") or primary_post.get("source_url")
        out.append({"score":score,"viral_score":round(viral,1),"editorial_score":round(editorial,1),
          "confidence":conf,"posts":len(ms),"social_sources":len(sources),"views":views,"reposts":reposts,
          "content_type":content,"official_attribution":official,"source_type":infos[0]["source_type"],
          "nonlocal_detected":nonlocal_only,"help_request":help_only,"opinion_detected":opinion_only,
          "advertising_detected":ad_only,"excluded_topic":excluded_only,"status":status,"action":action,
          "members":[m["post"] for m in ms],"text":texts[0] if texts else "",
          "primary_source": source_of(primary_post),"primary_url": primary_url,
          "source_urls": [m["post"].get("url") for m in ms if m["post"].get("url")]})

    out.sort(key=lambda x:x["score"],reverse=True)
    result={"generated_at":datetime.now().isoformat(timespec="seconds"),"clustering_version":"v10.14",
      "posts_analyzed":len(posts),"topic_count":len(out),
      "rules":{"help_requests_are_not_news":True,"social_reposts_are_not_independent_confirmation":True,
               "official_attribution_is_high_confidence":True,"official_source_names_detected":True,
               "help_requests_override_official_attribution":True,
               "same_event_dedup_before_status":True,
               "complaints_are_separate_from_news":True,
               "viral_complaint_can_be_signal":True,
               "viral_complaint_threshold":"viral>=60 OR views>=5000 OR reposts>=10 OR posts>=3",
               "help_request_patterns_extended":True,"opinion_patterns_extended":True,"official_signed_orders_detected":True,
               "nonlocal_cap":"watch"},
      "take_now":[x for x in out if x["status"]=="take_now"],
      "unconfirmed_signals":[x for x in out if x["status"]=="unconfirmed_signals"],
      "check":[x for x in out if x["status"]=="check"],"watch":[x for x in out if x["status"]=="watch"],
      "reject":[x for x in out if x["status"]=="reject"],"topics":out}
    OUTPUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    console_print(f"Готово: {len(posts)} постов -> {len(out)} тем")
    console_print(f"БРАТЬ {len(result['take_now'])} | СИГНАЛЫ {len(result['unconfirmed_signals'])} | ПРОВЕРИТЬ {len(result['check'])} | НАБЛЮДАТЬ {len(result['watch'])} | ОТБРОСИТЬ {len(result['reject'])}")

if __name__=="__main__":main()
