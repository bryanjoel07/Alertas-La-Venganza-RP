import asyncio
import unittest

from bugs import BugSystem
from feedback import FeedbackSystem
from photos import PhotoSystem
from recruitment import RecruitmentSystem
from suggestions import SuggestionSystem
from tickets import TicketSystem


class BackgroundLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_start_does_not_duplicate_tasks_or_repeat_installations(self):
        task=asyncio.create_task(asyncio.Event().wait())
        try:
            for cls in (BugSystem,FeedbackSystem,PhotoSystem,RecruitmentSystem,SuggestionSystem,TicketSystem):
                with self.subTest(system=cls.__name__):
                    system=object.__new__(cls);system.task=task
                    await system.start()
                    self.assertIs(system.task,task)
                    self.assertFalse(task.done())
        finally:
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
