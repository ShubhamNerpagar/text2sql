from __future__ import annotations
from app.services.market_service import MarketService

class WorkspaceService(MarketService):
    """Canonical workspace naming introduced in 7.0.

    MarketService remains as a compatibility shim for 6.x API/query internals. New code
    should prefer workspace terminology; country/market is optional metadata only.
    """
    def list_workspaces(self): return self.list_markets()
    def workspace(self,workspace_id:str): return self.context(workspace_id)
