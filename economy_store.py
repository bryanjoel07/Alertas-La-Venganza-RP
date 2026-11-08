"""Economía transaccional. No modifica tablas originales ni paga inscripciones."""

import hashlib
import json
import random
import re
import sqlite3
import time
import unicodedata
import uuid
from contextlib import closing, contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from backup import snapshot

PR = ZoneInfo("America/Puerto_Rico")
CATEGORY_ID = 1513422023626326257
REWARDS = {"first": 500, "second": 350, "third": 250, "participant": 100}
BANNERS = {
    "garaje": "Garaje en llamas",
    "salinas": "Salinas de noche",
    "parrilla": "Parrilla del Car Show",
}
PROFILE_PRODUCTS = [
    *(
        (f"banner-{art}", f"🖼️ {label}", "banner", 900, {"art": art, "label": label})
        for art, label in BANNERS.items()
    ),
    ("matricula-rp", "🏷️ Matrícula RP", "plate", 600, {"label": "Placa personalizada"}),
    (
        "firma-podio",
        "💬 Firma de podio",
        "signature",
        1200,
        {"label": "Firma personal"},
    ),
    (
        "vitrina-podios",
        "🏆 Vitrina de trofeos",
        "showcase",
        1500,
        {"label": "Tres podios ganados"},
    ),
]
SCHEMA = """
CREATE TABLE IF NOT EXISTS eco_config(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS eco_accounts(user_id INTEGER PRIMARY KEY,balance INTEGER NOT NULL DEFAULT 0 CHECK(balance>=0));
CREATE TABLE IF NOT EXISTS eco_ledger(id INTEGER PRIMARY KEY,op TEXT UNIQUE NOT NULL,user_id INTEGER NOT NULL,amount INTEGER NOT NULL,reason TEXT NOT NULL,actor INTEGER NOT NULL,created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS eco_products(sku TEXT PRIMARY KEY,name TEXT NOT NULL,kind TEXT NOT NULL,tier TEXT NOT NULL,price INTEGER NOT NULL CHECK(price>=0),payload TEXT NOT NULL,duration INTEGER NOT NULL DEFAULT 0,stock INTEGER,serial INTEGER NOT NULL DEFAULT 0,active INTEGER NOT NULL DEFAULT 1,revision INTEGER NOT NULL DEFAULT 1,campaign_end INTEGER,campaign_start INTEGER);
CREATE TABLE IF NOT EXISTS eco_rotations(week TEXT PRIMARY KEY,skus TEXT NOT NULL,ends INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS eco_quotes(id TEXT PRIMARY KEY,buyer INTEGER NOT NULL,recipient INTEGER NOT NULL,sku TEXT NOT NULL,price INTEGER NOT NULL,revision INTEGER NOT NULL,week TEXT NOT NULL,expires INTEGER NOT NULL,purchase_id TEXT);
CREATE TABLE IF NOT EXISTS eco_purchases(id TEXT PRIMARY KEY,quote TEXT UNIQUE NOT NULL,buyer INTEGER NOT NULL,recipient INTEGER NOT NULL,sku TEXT NOT NULL,price INTEGER NOT NULL,name TEXT NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL,duration INTEGER NOT NULL,edition INTEGER NOT NULL,status TEXT NOT NULL,created INTEGER NOT NULL,expires INTEGER,resource_id INTEGER,original_nick TEXT,delivery_state TEXT NOT NULL DEFAULT 'new');
CREATE TABLE IF NOT EXISTS eco_equipped(user_id INTEGER NOT NULL,slot TEXT NOT NULL,purchase_id TEXT NOT NULL,value TEXT NOT NULL,PRIMARY KEY(user_id,slot));
CREATE TABLE IF NOT EXISTS eco_sync(user_id INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS eco_resources(key TEXT PRIMARY KEY,resource_id INTEGER,state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS eco_wishes(user_id INTEGER NOT NULL,sku TEXT NOT NULL,PRIMARY KEY(user_id,sku));
CREATE TABLE IF NOT EXISTS eco_goals(user_id INTEGER PRIMARY KEY,sku TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS eco_participants(event_id INTEGER NOT NULL,user_id INTEGER NOT NULL,actor INTEGER NOT NULL,PRIMARY KEY(event_id,user_id));
CREATE TABLE IF NOT EXISTS eco_rewards(event_id INTEGER NOT NULL,user_id INTEGER NOT NULL,amount INTEGER NOT NULL,PRIMARY KEY(event_id,user_id));
CREATE TABLE IF NOT EXISTS eco_reward_rates(event_id INTEGER PRIMARY KEY,rates TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS eco_legacy_events(event_id INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS eco_audit(id INTEGER PRIMARY KEY,actor INTEGER NOT NULL,action TEXT NOT NULL,created INTEGER NOT NULL,sent INTEGER NOT NULL DEFAULT 0);
"""


SLOTS = {
    "badge": "insignia",
    "limited": "insignia",
    "title": "titulo",
    "theme": "tema",
    "color": "color",
    "custom_color": "color",
    "nickname": "prefijo",
    "bio": "frase",
    "celebration": "victoria",
    "banner": "banner",
    "plate": "matricula",
    "signature": "firma",
    "showcase": "vitrina",
    "souvenir": "recuerdo",
}


def clean_label(value, limit):
    value = " ".join(value.split())
    if (
        not value
        or len(value) > limit
        or any(c in "@<>`" or unicodedata.category(c) in {"Cc", "Cf"} for c in value)
    ):
        raise ValueError(
            f"Elige un texto sin menciones ni caracteres de control, de hasta {limit} caracteres."
        )
    return value


def outfit_for(p, value):
    kind = p["kind"]
    data = json.loads(p["payload"])
    if kind == "bundle":
        selections = {
            "tema": data["label"],
            "titulo": data["title"],
            "color": f"{data['color']:06X}",
        }
    else:
        slot = SLOTS.get(kind)
        if slot is None:
            raise ValueError("Este artículo se entrega automáticamente.")
        if kind == "custom_color":
            if (
                not re.fullmatch(r"#?[0-9a-fA-F]{6}", value)
                or int(value.lstrip("#"), 16) == 0
            ):
                raise ValueError(
                    "Indica un color hexadecimal visible, por ejemplo #0088FF."
                )
            value = value.lstrip("#").upper()
        elif kind == "color":
            value = f"{data['color']:06X}"
        elif kind in ("nickname", "bio"):
            value = clean_label(value, 8 if kind == "nickname" else 100)
        elif kind == "plate":
            value = clean_label(value, 10).upper()
            if not re.fullmatch(r"[A-Z0-9]+(?:-[A-Z0-9]+)*", value) or len(value) > 10:
                raise ValueError(
                    "La matrícula admite hasta 10 letras A–Z, números y guiones. Ejemplo: CHINO-7."
                )
        elif kind == "signature":
            value = clean_label(value, 100)
        else:
            value = data.get("label", p["name"])
        selections = {slot: value}
    return selections


def week_slot(now):
    local = datetime.fromtimestamp(now, PR)
    monday = (local - timedelta(days=local.weekday())).replace(
        hour=18, minute=30, second=0, microsecond=0
    )
    if local < monday:
        monday -= timedelta(days=7)
    return monday.date().isoformat(), int((monday + timedelta(days=7)).timestamp())


def catalog():
    rows = [
        (
            "insignia-fuego",
            "🔥 Insignia Fuego",
            "badge",
            "cheap",
            150,
            {"label": "🔥 Fuego"},
        ),
        (
            "insignia-rayo",
            "⚡ Insignia Rayo",
            "badge",
            "cheap",
            150,
            {"label": "⚡ Rayo"},
        ),
        (
            "titulo-calle",
            "🏷️ Espíritu de la Calle",
            "title",
            "cheap",
            250,
            {"label": "Espíritu de la Calle"},
        ),
        (
            "titulo-piloto",
            "🏷️ Piloto de La Venganza",
            "title",
            "cheap",
            250,
            {"label": "Piloto de La Venganza"},
        ),
        ("color-rojo", "🎨 Rojo Venganza", "color", "cheap", 300, {"color": 0xD60000}),
        ("color-azul", "🎨 Azul Eléctrico", "color", "cheap", 300, {"color": 0x168CFF}),
        ("biografia", "📜 Frase de perfil", "bio", "cheap", 350, {}),
        (
            "tema-neon",
            "🃏 Tarjeta Neón",
            "theme",
            "saving",
            800,
            {"color": 0x00E5D4, "label": "Neón"},
        ),
        (
            "tema-fuego",
            "🃏 Tarjeta Fuego",
            "theme",
            "saving",
            800,
            {"color": 0xFF6500, "label": "Fuego"},
        ),
        (
            "tema-oro",
            "🃏 Tarjeta Dorada",
            "theme",
            "saving",
            800,
            {"color": 0xF1C40F, "label": "Dorada"},
        ),
        ("prefijo", "✨ Prefijo del apodo", "nickname", "saving", 1000, {}),
        (
            "titulo-leyenda",
            "👑 Leyenda de La Venganza",
            "title",
            "saving",
            1500,
            {"label": "Leyenda de La Venganza"},
        ),
        ("color-libre", "🌈 Color personalizado", "custom_color", "saving", 2000, {}),
        (
            "pack-magnate",
            "💎 Colección Magnate",
            "bundle",
            "exclusive",
            3000,
            {"title": "Magnate", "color": 0x9B59B6, "label": "💎 Magnate"},
        ),
        (
            "pack-venganza",
            "🔱 Colección Venganza",
            "bundle",
            "exclusive",
            3000,
            {"title": "Élite Venganza", "color": 0xE74C3C, "label": "🔱 Élite"},
        ),
        (
            "victoria-oro",
            "🏆 Celebración Dorada",
            "celebration",
            "exclusive",
            3500,
            {"color": 0xF1C40F, "label": "🏆 Victoria de Leyenda"},
        ),
        (
            "sala-voz",
            "🔊 Sala personal · 7 días",
            "voice",
            "exclusive",
            4000,
            {"label": "Sala personal"},
        ),
        (
            "aniversario-2026",
            "🌟 Edición Aniversario 2026",
            "limited",
            "limited",
            5000,
            {"label": "🌟 Aniversario 2026", "color": 0xFFD700},
        ),
    ]
    return [
        dict(
            sku=s,
            name=n,
            kind=k,
            tier=t,
            price=p,
            payload=json.dumps(v),
            duration=604800 if k == "voice" else 0,
            stock=25 if k == "limited" else None,
            campaign_end=int(datetime(2027, 1, 1, tzinfo=PR).timestamp())
            if k == "limited"
            else None,
        )
        for s, n, k, t, p, v in rows
    ]


class EconomyStore:
    def __init__(self, path):
        self.path = str(path)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def initialize(self):
        with closing(sqlite3.connect(self.path)) as db:
            installed = db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='eco_config'"
            ).fetchone()
            profile_installed = installed and self.get(db, "profile_collection")
        if not profile_installed:
            name = f"economy-before-{time.time_ns()}.sqlite3"
            snapshot(self.path, Path(self.path).parent / "backups" / name)
        with self.db() as db:
            for statement in SCHEMA.split(";"):
                if statement.strip():
                    db.execute(statement)
            if not self.get(db, "installed"):
                for p in catalog():
                    db.execute(
                        "INSERT OR IGNORE INTO eco_products(sku,name,kind,tier,price,payload,duration,stock,campaign_end) VALUES (:sku,:name,:kind,:tier,:price,:payload,:duration,:stock,:campaign_end)",
                        p,
                    )
                db.execute(
                    "INSERT OR IGNORE INTO eco_legacy_events SELECT id FROM events WHERE status IN ('finished','closed')"
                )
                self.set(db, "installed", str(int(time.time())))
                self.set(db, "category", str(CATEGORY_ID))
                self.set(db, "rewards", json.dumps(REWARDS))
            if not self.get(db, "profile_collection"):
                for sku, name, kind, price, payload in PROFILE_PRODUCTS:
                    db.execute(
                        "INSERT OR IGNORE INTO eco_products(sku,name,kind,tier,price,payload) VALUES (?,?,?,'profile',?,?)",
                        (sku, name, kind, price, json.dumps(payload)),
                    )
                self.set(db, "profile_collection", 1)

    @staticmethod
    def get(db, key, default=""):
        row = db.execute("SELECT value FROM eco_config WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    @staticmethod
    def set(db, key, value):
        db.execute("INSERT OR REPLACE INTO eco_config VALUES (?,?)", (key, str(value)))

    def config(self, key, value=None, actor=0):
        with self.db() as db:
            if value is not None:
                self.set(db, key, value)
                self.audit(db, actor, f"Configuración {key} actualizada")
            return self.get(db, key)

    @staticmethod
    def audit(db, actor, action):
        db.execute(
            "INSERT INTO eco_audit(actor,action,created) VALUES (?,?,?)",
            (actor, action[:1500], int(time.time())),
        )

    @staticmethod
    def credit(db, user, amount, op, reason, actor):
        if db.execute("SELECT 1 FROM eco_ledger WHERE op=?", (op,)).fetchone():
            return False
        db.execute("INSERT OR IGNORE INTO eco_accounts(user_id) VALUES (?)", (user,))
        if not db.execute(
            "UPDATE eco_accounts SET balance=balance+? WHERE user_id=? AND balance+?>=0",
            (amount, user, amount),
        ).rowcount:
            raise ValueError("Saldo insuficiente. No se aplicó ningún cambio.")
        db.execute(
            "INSERT INTO eco_ledger(op,user_id,amount,reason,actor,created) VALUES (?,?,?,?,?,?)",
            (op, user, amount, reason[:300], actor, int(time.time())),
        )
        return True

    def adjust(self, user, amount, reason, actor, op):
        if not reason.strip() or not amount or abs(amount) > 1000000:
            raise ValueError(
                "Indica un motivo y una cantidad entre -1.000.000 y 1.000.000, distinta de cero."
            )
        with self.db() as db:
            if self.credit(db, user, amount, "adjust:" + op, reason, actor):
                self.audit(db, actor, f"Ajuste {amount:+} a {user}: {reason}")

    def account(self, user):
        with self.db() as db:
            row = db.execute(
                "SELECT balance FROM eco_accounts WHERE user_id=?", (user,)
            ).fetchone()
            goal = db.execute(
                "SELECT p.name,p.price FROM eco_goals g JOIN eco_products p ON p.sku=g.sku WHERE g.user_id=?",
                (user,),
            ).fetchone()
            return {
                "balance": row[0] if row else 0,
                "goal": dict(goal) if goal else None,
            }

    def rotation_in(self, db, now):
        week, ends = week_slot(now)
        row = db.execute("SELECT * FROM eco_rotations WHERE week=?", (week,)).fetchone()
        if not row:
            selected = []
            rng = random.Random(int(hashlib.sha256(week.encode()).hexdigest(), 16))
            for tier, count in [
                ("cheap", 2),
                ("saving", 2),
                ("exclusive", 1),
                ("limited", 1),
            ]:
                available = list(
                    db.execute(
                        "SELECT sku,kind FROM eco_products WHERE active=1 AND tier=? AND (stock IS NULL OR stock>0) AND (campaign_end IS NULL OR campaign_end>?) AND (campaign_start IS NULL OR campaign_start<=?) ORDER BY sku",
                        (tier, now, now),
                    )
                )
                candidates = [
                    r["sku"]
                    for r in available
                    if tier != "exclusive" or r["kind"] == "bundle"
                ]
                selected += rng.sample(candidates, min(count, len(candidates)))
                if tier == "exclusive":
                    extras = [r["sku"] for r in available if r["kind"] != "bundle"]
                    selected += rng.sample(extras, min(1, len(extras)))
            db.execute(
                "INSERT INTO eco_rotations VALUES (?,?,?)",
                (week, json.dumps(selected), ends),
            )
            row = db.execute(
                "SELECT * FROM eco_rotations WHERE week=?", (week,)
            ).fetchone()
        return dict(row)

    def rotation(self, now=None, *, user=None):
        with self.db() as db:
            r = self.rotation_in(db, int(time.time()) if now is None else now)
            r["products"] = [
                dict(
                    db.execute(
                        "SELECT * FROM eco_products WHERE sku=?", (s,)
                    ).fetchone()
                )
                for s in json.loads(r["skus"])
            ]
            r["products"].extend(
                dict(p)
                for p in db.execute(
                    "SELECT * FROM eco_products WHERE tier='profile' AND active=1 ORDER BY price,sku"
                )
            )
            if user is not None:
                for event in self.eligible_events(db, user, limit=6):
                    souvenir = self.event_souvenir(db, event)
                    if souvenir["active"]:
                        r["products"].append(dict(souvenir))
            return r

    @staticmethod
    def eligible_events(db, user, event_id=None, limit=1):
        return db.execute(
            """SELECT e.id,e.title,e.starts_at FROM events e
            WHERE (e.status='finished' OR (e.status='closed' AND COALESCE(e.winner1,'')!=''))
            AND (? IS NULL OR e.id=?)
            AND (? IN (e.winner1,e.winner2,e.winner3) OR EXISTS
                (SELECT 1 FROM eco_participants p WHERE p.event_id=e.id AND p.user_id=?))
            ORDER BY e.id DESC LIMIT ?""",
            (event_id, event_id, str(user), user, limit),
        ).fetchall()

    @staticmethod
    def event_souvenir(db, event):
        sku = f"recuerdo-{event['id']}"
        label = f"#{event['id']} · {event['title']}"[:65]
        db.execute(
            """INSERT OR IGNORE INTO eco_products(sku,name,kind,tier,price,payload)
            VALUES (?,?,'souvenir','event',250,?)""",
            (
                sku,
                "🎟️ " + label,
                json.dumps(
                    dict(label=label, event=event["id"], date=event["starts_at"])
                ),
            ),
        )
        return db.execute("SELECT * FROM eco_products WHERE sku=?", (sku,)).fetchone()

    def offer(self, db, sku, rotation, buyer, recipient):
        if sku.startswith("recuerdo-"):
            if buyer != recipient:
                raise ValueError(
                    "Los recuerdos de evento son personales y no pueden regalarse."
                )
            number = sku.removeprefix("recuerdo-")
            events = (
                self.eligible_events(db, recipient, int(number))
                if re.fullmatch(r"[1-9][0-9]{0,15}", number)
                else []
            )
            if not events:
                raise ValueError(
                    "Este recuerdo requiere un podio o asistencia confirmada por Staff en el evento finalizado."
                )
            return self.event_souvenir(db, events[0])
        p = db.execute("SELECT * FROM eco_products WHERE sku=?", (sku,)).fetchone()
        if not p or (
            p["tier"] != "profile" and sku not in json.loads(rotation["skus"])
        ):
            raise ValueError("Este artículo no está disponible en la rotación actual.")
        return p

    def products(self):
        with self.db() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM eco_products ORDER BY tier,price,sku"
                )
            ]

    def showcase(self, user, purchase):
        with self.db() as db:
            wins = [
                dict(r)
                for r in db.execute(
                    """SELECT id,title,starts_at,winner1,winner2,winner3
                FROM events WHERE ? IN (winner1,winner2,winner3) ORDER BY starts_at DESC,id DESC""",
                    (str(user),),
                )
            ]
            by_id = {str(r["id"]): r for r in wins}
            slots = [
                by_id.get(self.get(db, f"vitrina:{purchase}:{pos}"))
                for pos in range(1, 4)
            ]
            pinned = {r["id"] for r in slots if r}
            automatic = iter(r for r in wins if r["id"] not in pinned)
            return [r or next(automatic, None) for r in slots]

    def pin_trophy(self, user, position, event):
        with self.db() as db:
            owned = db.execute(
                """SELECT p.id FROM eco_equipped e JOIN eco_purchases p ON e.purchase_id=p.id
                WHERE e.user_id=? AND e.slot='vitrina' AND p.status='delivered'""",
                (user,),
            ).fetchone()
            if not owned or position not in (1, 2, 3):
                raise ValueError("Equipa tu vitrina y elige un espacio del 1 al 3.")
            if not db.execute(
                "SELECT 1 FROM events WHERE id=? AND ? IN (winner1,winner2,winner3)",
                (event, str(user)),
            ).fetchone():
                raise ValueError("Solo puedes exhibir un podio que ganaste.")
            for pos in range(1, 4):
                key = f"vitrina:{owned['id']}:{pos}"
                if self.get(db, key) == str(event):
                    self.set(db, key, "")
            self.set(db, f"vitrina:{owned['id']}:{position}", event)

    def collection_price(self, sku, price, active, actor):
        with self.db() as db:
            if (
                price < 0
                or price > 1_000_000
                or not db.execute(
                    "UPDATE eco_products SET price=?,active=?,revision=revision+1 WHERE sku=? AND tier IN ('profile','event')",
                    (price, active, sku),
                ).rowcount
            ):
                raise ValueError(
                    "Elige un artículo de colección y un precio entre 0 y 1.000.000."
                )
            self.audit(db, actor, f"Artículo {sku} · precio {price} · activo {active}")

    def quote(self, buyer, recipient, sku, now=None):
        now = int(time.time()) if now is None else now
        with self.db() as db:
            r = self.rotation_in(db, now)
            p = self.offer(db, sku, r, buyer, recipient)
            if (
                not p["active"]
                or (p["campaign_start"] and p["campaign_start"] > now)
                or (p["campaign_end"] and p["campaign_end"] <= now)
            ):
                raise ValueError(
                    "Este artículo no está disponible en la rotación actual."
                )
            if p["stock"] is not None and p["stock"] <= 0:
                raise ValueError("Artículo agotado.")
            if db.execute(
                "SELECT 1 FROM eco_purchases WHERE recipient=? AND sku=? AND status!='refunded' AND (expires IS NULL OR expires>?)",
                (recipient, sku, now),
            ).fetchone():
                raise ValueError(
                    "El destinatario ya tiene este artículo o una compra pendiente."
                )
            q = dict(p)
            q.update(
                id=uuid.uuid4().hex,
                buyer=buyer,
                recipient=recipient,
                week=r["week"],
                expires=min(now + 180, r["ends"]),
            )
            db.execute(
                "INSERT INTO eco_quotes(id,buyer,recipient,sku,price,revision,week,expires) VALUES (:id,:buyer,:recipient,:sku,:price,:revision,:week,:expires)",
                q,
            )
            return q

    def buy(self, quote_id, buyer, now=None, *, value=""):
        now = int(time.time()) if now is None else now
        with self.db() as db:
            q = db.execute(
                "SELECT * FROM eco_quotes WHERE id=? AND buyer=?", (quote_id, buyer)
            ).fetchone()
            if not q:
                raise ValueError("Confirmación no autorizada.")
            if q["purchase_id"]:
                return dict(
                    db.execute(
                        "SELECT * FROM eco_purchases WHERE id=?", (q["purchase_id"],)
                    ).fetchone()
                )
            r = self.rotation_in(db, now)
            p = self.offer(db, q["sku"], r, buyer, q["recipient"])
            if (
                now >= q["expires"]
                or r["week"] != q["week"]
                or not p["active"]
                or p["revision"] != q["revision"]
                or (p["campaign_start"] and p["campaign_start"] > now)
                or (p["campaign_end"] and p["campaign_end"] <= now)
            ):
                raise ValueError("La oferta cambió o expiró. Abre otra vista previa.")
            if p["stock"] is not None and p["stock"] <= 0:
                raise ValueError("Artículo agotado; no se cobró.")
            if db.execute(
                "SELECT 1 FROM eco_purchases WHERE recipient=? AND sku=? AND status!='refunded' AND (expires IS NULL OR expires>?)",
                (q["recipient"], q["sku"], now),
            ).fetchone():
                raise ValueError("El destinatario ya tiene el artículo; no se cobró.")
            key = uuid.uuid4().hex
            gift = q["recipient"] != buyer
            reason = (
                "Regalo para " + str(q["recipient"]) + " · " if gift else "Compra "
            ) + p["name"]
            self.credit(db, buyer, -q["price"], "buy:" + key, reason, buyer)
            if gift:
                self.credit(
                    db,
                    q["recipient"],
                    0,
                    "gift:" + key,
                    "Regalo de " + str(buyer) + " · " + p["name"],
                    buyer,
                )
            db.execute(
                "UPDATE eco_products SET serial=serial+1,stock=CASE WHEN stock IS NULL THEN NULL ELSE stock-1 END WHERE sku=?",
                (p["sku"],),
            )
            edition = p["serial"] + 1
            status = "pending" if p["kind"] == "voice" else "delivered"
            db.execute(
                """INSERT INTO eco_purchases(id,quote,buyer,recipient,sku,price,name,kind,payload,duration,edition,status,created)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    key,
                    quote_id,
                    buyer,
                    q["recipient"],
                    p["sku"],
                    q["price"],
                    p["name"],
                    p["kind"],
                    p["payload"],
                    p["duration"],
                    edition,
                    status,
                    now,
                ),
            )
            db.execute(
                "UPDATE eco_quotes SET purchase_id=? WHERE id=?", (key, quote_id)
            )
            self.audit(
                db,
                buyer,
                f"Compra {key} · {p['name']} · {q['price']} monedas · destinatario {q['recipient']} · edición {edition}",
            )
            if p["kind"] != "voice":
                self._write_outfit(db, q["recipient"], key, outfit_for(p, value))
            self.collection_bonus(db, q["recipient"], now)
            return dict(
                db.execute("SELECT * FROM eco_purchases WHERE id=?", (key,)).fetchone()
            )

    def collection_bonus(self, db, user, now):
        owned = {
            r[0]
            for r in db.execute(
                "SELECT sku FROM eco_purchases WHERE recipient=? AND status='delivered'",
                (user,),
            )
        }
        if {"insignia-fuego", "tema-fuego"}.issubset(
            owned
        ) and "coleccion-fuego" not in owned:
            key = uuid.uuid4().hex
            db.execute(
                """INSERT INTO eco_purchases(id,quote,buyer,recipient,sku,price,name,kind,payload,duration,edition,status,created)
                VALUES (?,?,?,?,?,0,?,?,?,0,1,'delivered',?)""",
                (
                    key,
                    "bonus:" + str(user),
                    user,
                    user,
                    "coleccion-fuego",
                    "🔥 Colección Fuego completa",
                    "badge",
                    json.dumps({"label": "🔥 Coleccionista Fuego"}),
                    now,
                ),
            )

    def inventory(self, user):
        with self.db() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM eco_purchases WHERE recipient=? AND status!='refunded' ORDER BY created DESC,id",
                    (user,),
                )
            ]

    def purchase(self, key, user=None):
        with self.db() as db:
            p = db.execute("SELECT * FROM eco_purchases WHERE id=?", (key,)).fetchone()
            if not p or (user is not None and p["recipient"] != user):
                raise ValueError("Artículo no encontrado en tu inventario.")
            return dict(p)

    def unequip(self, user, slot):
        with self.db() as db:
            db.execute(
                "DELETE FROM eco_equipped WHERE user_id=? AND slot=?", (user, slot)
            )
            if slot in ("color", "titulo", "prefijo"):
                db.execute("INSERT OR IGNORE INTO eco_sync VALUES (?)", (user,))

    def set_outfit(self, user, key, selections):
        with self.db() as db:
            if not db.execute(
                "SELECT 1 FROM eco_purchases WHERE recipient=? AND id=? AND status='delivered' AND (expires IS NULL OR expires>?)",
                (user, key, int(time.time())),
            ).fetchone():
                raise ValueError("Artículo no disponible en tu inventario.")
            self._write_outfit(db, user, key, selections)

    @staticmethod
    def _write_outfit(db, user, key, selections):
        for slot, value in selections.items():
            db.execute(
                "INSERT OR REPLACE INTO eco_equipped VALUES (?,?,?,?)",
                (user, slot, key, value),
            )
        if selections.keys() & {"color", "titulo", "prefijo"}:
            db.execute("INSERT OR IGNORE INTO eco_sync VALUES (?)", (user,))

    def runtime_config(self, key, value):
        with self.db() as db:
            self.set(db, key, value)

    def equipped(self, user):
        with self.db() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT e.*,p.kind,p.payload,p.name,p.edition,p.resource_id,p.original_nick FROM eco_equipped e JOIN eco_purchases p ON p.id=e.purchase_id WHERE e.user_id=? AND p.status='delivered' AND (p.expires IS NULL OR p.expires>?)",
                    (user, int(time.time())),
                )
            ]

    def resource(self, key, value=None, state=None):
        with self.db() as db:
            if state is not None:
                db.execute(
                    "INSERT OR REPLACE INTO eco_resources VALUES (?,?,?)",
                    (key, value, state),
                )
            r = db.execute("SELECT * FROM eco_resources WHERE key=?", (key,)).fetchone()
            return dict(r) if r else None

    def delivery(self, key, resource_id, state="delivered", original_nick=None):
        with self.db() as db:
            db.execute(
                "UPDATE eco_purchases SET resource_id=?,status=?,delivery_state='ready',expires=CASE WHEN duration>0 THEN COALESCE(expires,?+duration) ELSE NULL END,original_nick=COALESCE(original_nick,?) WHERE id=?",
                (resource_id, state, int(time.time()), original_nick, key),
            )

    def refund(self, key, actor, reason):
        if not reason.strip():
            raise ValueError("Indica el motivo de la devolución.")
        with self.db() as db:
            p = db.execute("SELECT * FROM eco_purchases WHERE id=?", (key,)).fetchone()
            if not p:
                raise ValueError("Compra no encontrada.")
            if p["status"] == "refunded":
                return
            if p["quote"].startswith("bonus:"):
                raise ValueError("Una insignia de colección no es una compra.")
            if db.execute(
                "SELECT 1 FROM eco_equipped WHERE purchase_id=?", (key,)
            ).fetchone():
                db.execute("DELETE FROM eco_equipped WHERE purchase_id=?", (key,))
                db.execute(
                    "INSERT OR IGNORE INTO eco_sync VALUES (?)", (p["recipient"],)
                )
            self.credit(
                db,
                p["buyer"],
                p["price"],
                "refund:" + key,
                "Devolución: " + reason,
                actor,
            )
            db.execute("UPDATE eco_purchases SET status='refunded' WHERE id=?", (key,))
            db.execute(
                "UPDATE eco_products SET stock=stock+1 WHERE sku=? AND stock IS NOT NULL",
                (p["sku"],),
            )
            if p["sku"] in ("insignia-fuego", "tema-fuego"):
                bonus = "bonus:" + str(p["recipient"])
                db.execute(
                    "DELETE FROM eco_equipped WHERE purchase_id IN (SELECT id FROM eco_purchases WHERE quote=?)",
                    (bonus,),
                )
                db.execute("DELETE FROM eco_purchases WHERE quote=?", (bonus,))
            self.audit(db, actor, f"Devolución {key}: {reason}")

    def participant(self, event, user, present, actor):
        with self.db() as db:
            e = db.execute("SELECT status FROM events WHERE id=?", (event,)).fetchone()
            if (
                not e
                or e["status"] == "closed"
                or db.execute(
                    "SELECT 1 FROM eco_legacy_events WHERE event_id=?", (event,)
                ).fetchone()
            ):
                raise ValueError(
                    "Evento no elegible para monedas o anterior a la activación."
                )
            if present:
                db.execute(
                    "INSERT OR REPLACE INTO eco_participants VALUES (?,?,?)",
                    (event, user, actor),
                )
            else:
                db.execute(
                    "DELETE FROM eco_participants WHERE event_id=? AND user_id=?",
                    (event, user),
                )
            if e["status"] == "finished":
                self.reconcile_in(db, event, actor)
            self.audit(
                db, actor, f"Participación evento {event}, jugador {user}: {present}"
            )

    def reconcile_in(self, db, event, actor):
        e = db.execute("SELECT * FROM events WHERE id=?", (event,)).fetchone()
        if (
            not e
            or e["status"] != "finished"
            or db.execute(
                "SELECT 1 FROM eco_legacy_events WHERE event_id=?", (event,)
            ).fetchone()
        ):
            return 0
        saved = db.execute(
            "SELECT rates FROM eco_reward_rates WHERE event_id=?", (event,)
        ).fetchone()
        rates = (
            json.loads(saved[0])
            if saved
            else json.loads(self.get(db, "rewards", json.dumps(REWARDS)))
        )
        db.execute(
            "INSERT OR IGNORE INTO eco_reward_rates VALUES (?,?)",
            (event, json.dumps(rates)),
        )
        desired = {
            r[0]: rates["participant"]
            for r in db.execute(
                "SELECT user_id FROM eco_participants WHERE event_id=?", (event,)
            )
        }
        for column, position in [
            ("winner3", "third"),
            ("winner2", "second"),
            ("winner1", "first"),
        ]:
            if e[column]:
                desired[int(e[column])] = rates[position]
        paid = dict(
            db.execute(
                "SELECT user_id,amount FROM eco_rewards WHERE event_id=?", (event,)
            )
        )
        changes = {
            user: desired.get(user, 0) - paid.get(user, 0)
            for user in paid.keys() | desired.keys()
        }
        for user, difference in changes.items():
            if difference:
                self.credit(
                    db,
                    user,
                    difference,
                    "reward:" + uuid.uuid4().hex,
                    f"Resultados del evento #{event}",
                    actor,
                )
                db.execute(
                    "INSERT OR REPLACE INTO eco_rewards VALUES (?,?,?)",
                    (event, user, desired.get(user, 0)),
                )
        return {user: amount for user, amount in changes.items() if amount}

    def correct(self, event, winners, actor, expected=None):
        """Preview in a savepoint. On confirmation verify that the same adjustments still apply."""
        with self.db() as db:
            row = db.execute("SELECT * FROM events WHERE id=?", (event,)).fetchone()
            if (
                not row
                or row["status"] != "finished"
                or db.execute(
                    "SELECT 1 FROM eco_legacy_events WHERE event_id=?", (event,)
                ).fetchone()
            ):
                raise ValueError(
                    "Elige un evento finalizado después de activar la economía."
                )
            if len(set(winners)) != 3:
                raise ValueError("Elige tres jugadores distintos.")
            before = [row[k] for k in ("winner1", "winner2", "winner3")]
            db.execute("SAVEPOINT preview")
            db.execute(
                "UPDATE events SET winner1=?,winner2=?,winner3=? WHERE id=?",
                (*map(str, winners), event),
            )
            changes = self.reconcile_in(db, event, actor)
            result = (before, changes)
            if expected is None:
                db.execute("ROLLBACK TO preview")
            elif result != expected:
                raise ValueError("Los resultados cambiaron. Revisa otra vista previa.")
            else:
                self.audit(
                    db,
                    actor,
                    f"Corrección del podio #{event}: {before} → {winners}. Ajustes: {changes}",
                )
            return result

    def rows(self, query, args=()):
        with self.db() as db:
            return [dict(r) for r in db.execute(query, args)]

    def preferences(self, user, sku, action):
        with self.db() as db:
            if (
                sku
                and not db.execute(
                    "SELECT 1 FROM eco_products WHERE sku=?", (sku,)
                ).fetchone()
            ):
                raise ValueError("Producto desconocido.")
            if action == "meta":
                db.execute("DELETE FROM eco_goals WHERE user_id=?", (user,))
                if sku:
                    db.execute("INSERT INTO eco_goals VALUES (?,?)", (user, sku))
            elif action == "agregar" and sku:
                db.execute("INSERT OR IGNORE INTO eco_wishes VALUES (?,?)", (user, sku))
            elif action == "quitar":
                db.execute(
                    "DELETE FROM eco_wishes WHERE user_id=? AND sku=?", (user, sku)
                )
            return [
                r[0]
                for r in db.execute(
                    "SELECT sku FROM eco_wishes WHERE user_id=? ORDER BY sku", (user,)
                )
            ]

    def save_product(
        self,
        actor,
        sku,
        name,
        kind,
        tier,
        price,
        stock,
        duration,
        active,
        payload,
        end,
        start=None,
    ):
        if sku.startswith("recuerdo-") or sku in {item[0] for item in PROFILE_PRODUCTS}:
            raise ValueError(
                "Usa /economia coleccion para cambiar el precio o activar este artículo."
            )
        if (
            not sku
            or len(sku) > 50
            or not sku.isascii()
            or not all(c.isalnum() or c == "-" for c in sku)
        ):
            raise ValueError("Usa un código de hasta 50 letras, números o guiones.")
        if kind not in {p["kind"] for p in catalog()} or tier not in {
            "cheap",
            "saving",
            "exclusive",
            "limited",
        }:
            raise ValueError("Tipo o categoría desconocidos.")
        if (
            not name.strip()
            or len(name) > 70
            or not 0 <= price <= 1000000
            or (stock is not None and stock < 0)
        ):
            raise ValueError("Revisa el nombre, precio y existencias.")
        if kind == "voice" and duration != 604800 or kind != "voice" and duration:
            raise ValueError(
                "La sala dura siete días. Los demás artículos son permanentes."
            )
        if start and end and start >= end:
            raise ValueError("El inicio de campaña debe ser anterior al cierre.")
        if tier == "limited" and (not end or stock is None):
            raise ValueError(
                "Las ediciones limitadas requieren fecha de cierre y unidades."
            )
        with self.db() as db:
            db.execute(
                """INSERT INTO eco_products(sku,name,kind,tier,price,stock,duration,active,payload,campaign_end,campaign_start)
                VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(sku) DO UPDATE SET name=excluded.name,kind=excluded.kind,tier=excluded.tier,
                price=excluded.price,stock=excluded.stock,duration=excluded.duration,active=excluded.active,payload=excluded.payload,
                campaign_start=excluded.campaign_start,campaign_end=excluded.campaign_end,revision=revision+1""",
                (
                    sku,
                    name,
                    kind,
                    tier,
                    price,
                    stock,
                    duration,
                    active,
                    json.dumps(payload),
                    end,
                    start,
                ),
            )
            self.audit(
                db,
                actor,
                f"Producto {sku} actualizado · {price} monedas · activo {active}",
            )

    def schedule(self, actor, week, skus):
        start = datetime.strptime(week, "%Y-%m-%d").replace(
            hour=18, minute=30, tzinfo=PR
        )
        if (
            start.weekday() != 0
            or start.timestamp() <= time.time()
            or len(skus) != len(set(skus))
        ):
            raise ValueError("Elige un lunes futuro y códigos sin repetir.")
        with self.db() as db:
            tiers = []
            bundle = False
            for sku in skus:
                p = db.execute(
                    "SELECT * FROM eco_products WHERE sku=? AND active=1", (sku,)
                ).fetchone()
                if (
                    not p
                    or p["stock"] == 0
                    or (p["campaign_start"] and p["campaign_start"] > start.timestamp())
                    or (p["campaign_end"] and p["campaign_end"] <= start.timestamp())
                ):
                    raise ValueError("Producto no disponible para esa semana: " + sku)
                tiers.append(p["tier"])
                bundle |= p["tier"] == "exclusive" and p["kind"] == "bundle"
            limited = db.execute(
                "SELECT 1 FROM eco_products WHERE active=1 AND tier='limited' AND (stock IS NULL OR stock>0) AND campaign_end>? AND (campaign_start IS NULL OR campaign_start<=?)",
                (start.timestamp(), start.timestamp()),
            ).fetchone()
            if not bundle or sorted(tiers) != sorted(
                ["cheap"] * 2
                + ["saving"] * 2
                + ["exclusive"]
                + (["limited"] if limited else [])
            ):
                raise ValueError(
                    "Incluye 2 baratos, 2 de ahorro, 1 exclusivo y 1 limitado si hay campaña."
                )
            db.execute(
                "INSERT OR REPLACE INTO eco_rotations VALUES (?,?,?)",
                (week, json.dumps(skus), week_slot(start.timestamp())[1]),
            )
            self.audit(db, actor, f"Rotación programada {week}: {skus}")
