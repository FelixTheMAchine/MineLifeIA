"""Night policy for the implemented local refuge, without suppressing the physical danger gate."""
class NightSurvivalManager:
    def __init__(self,construction):
        self.construction=construction

    def propose(self,observation):
        return self.construction.propose(observation,night=True)

    @property
    def reason(self):
        return self.construction.reason
