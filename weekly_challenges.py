"""Weekly bonuses for staff-confirmed activity. Claims and credits are atomic."""
from datetime import datetime, timedelta
import time

from economy_store import PR

GOALS = (
    ('participar', 'Participar en un evento confirmado por staff', 150),
    ('podio', 'Conseguir un podio en un evento', 200),
    ('reunion', 'Asistir a una reunión general confirmada por staff', 100),
)
SCHEMA = '''CREATE TABLE IF NOT EXISTS eco_weekly_claims(
 week TEXT NOT NULL,user_id INTEGER NOT NULL,goal TEXT NOT NULL,amount INTEGER NOT NULL,
 created INTEGER NOT NULL,PRIMARY KEY(week,user_id,goal));'''


def week_bounds(now):
    local = datetime.fromtimestamp(now, PR)
    start = (local - timedelta(days=local.weekday())).replace(hour=0,minute=0,second=0,microsecond=0)
    return start.date().isoformat(), int(start.timestamp()), int((start+timedelta(days=7)).timestamp())


class WeeklyChallenges:
    def __init__(self, store):
        self.store = store

    def initialize(self):
        with self.store.db() as db:
            db.executescript(SCHEMA)
            if not self.store.get(db, 'challenges_since'):
                self.store.set(db, 'challenges_since', int(time.time()))

    def progress_in(self, db, user, now):
        week,start,end = week_bounds(now)
        start = max(start,int(self.store.get(db,'challenges_since',str(now))))
        # Event timestamps may use UTC or PR; compare using SQLite's UTC normalizer.
        eligible = "status='finished' AND unixepoch(starts_at)>=? AND unixepoch(starts_at)<?"
        participating = db.execute(f'''SELECT 1 FROM events e JOIN eco_participants p ON p.event_id=e.id
            WHERE p.user_id=? AND p.actor IS NOT NULL AND {eligible} LIMIT 1''',(user,start,end)).fetchone()
        podium = db.execute(f'''SELECT 1 FROM events WHERE {eligible}
            AND (winner1=? OR winner2=? OR winner3=?) LIMIT 1''',(start,end,str(user),str(user),str(user))).fetchone()
        meeting = db.execute('''SELECT 1 FROM meetings m JOIN meeting_attendance a ON a.meeting_id=m.id
            WHERE m.kind='general' AND m.status='finished' AND m.starts_at>=? AND m.starts_at<?
            AND a.user_id=? AND a.present=1 AND a.recorded_by IS NOT NULL LIMIT 1''',(start,end,user)).fetchone()
        fulfilled = dict(zip(('participar','podio','reunion'),map(bool,(participating,podium,meeting))))
        claimed = {r[0] for r in db.execute('SELECT goal FROM eco_weekly_claims WHERE week=? AND user_id=?',(week,user))}
        return dict(week=week,ends=end,goals=[dict(key=k,label=label,reward=reward,done=fulfilled[k],claimed=k in claimed) for k,label,reward in GOALS])

    def progress(self,user,now=None):
        with self.store.db() as db:
            return self.progress_in(db,user,int(time.time()) if now is None else now)

    def claim(self,user,now=None):
        now = int(time.time()) if now is None else now
        with self.store.db() as db:
            progress = self.progress_in(db,user,now)
            amount = 0
            for goal in progress['goals']:
                if not goal['done'] or goal['claimed']:
                    continue
                op = f"weekly:{progress['week']}:{user}:{goal['key']}"
                if self.store.credit(db,user,goal['reward'],op,goal['label'],user):
                    db.execute('INSERT INTO eco_weekly_claims VALUES (?,?,?,?,?)',
                               (progress['week'],user,goal['key'],goal['reward'],now))
                    amount += goal['reward']
            if amount:
                self.store.audit(db,user,f"Retos semanales {progress['week']}: +{amount}")
            return amount
