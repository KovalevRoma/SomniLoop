"""Count completed logical work, independently of elapsed time and LLM retries."""


class WorkPlan:
    def __init__(self, fragments, people, connections):
        self.totals = {
            "prepare": 1,
            "analyze": fragments,
            "merge": people,
            "connections": connections,
            "links": 1,
            "save": 1,
        }
        self.completed = dict.fromkeys(self.totals, 0)
        self.completed["prepare"] = 1

    def finish(self, phase, count):
        self.completed[phase] = max(self.completed[phase], min(count, self.totals[phase]))

    def snapshot(self, phase):
        done, total = sum(self.completed.values()), sum(self.totals.values())
        return {
            "work_done": done,
            "work_total": total,
            "percent": 100 * done / total,
            "stage_done": self.completed[phase],
            "stage_total": self.totals[phase],
        }
