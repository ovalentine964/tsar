"""Position recovery — verify stop-losses on startup."""


class PositionRecovery:
    def __init__(self, exchange_gateway, risk_engine):
        self.exchange = exchange_gateway
        self.risk = risk_engine

    async def verify_stop_losses(self):
        """On startup, check all open positions have active stop-losses."""
        positions = await self.exchange.get_positions()
        orders = await self.exchange.get_open_orders()

        stop_symbols = {o.symbol for o in orders if o.type == "stop_market"}

        for pos in positions:
            if pos.symbol not in stop_symbols:
                # Missing stop-loss — place it
                sl_price = pos.entry_price * (1 - 0.02) if pos.side == "buy" else pos.entry_price * (1 + 0.02)
                await self.exchange.create_order(
                    symbol=pos.symbol,
                    side="sell" if pos.side == "buy" else "buy",
                    type="stop_market",
                    amount=pos.amount,
                    price=sl_price
                )
