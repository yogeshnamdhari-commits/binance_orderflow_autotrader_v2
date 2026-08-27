from app.orderbook import LocalOrderBook
from app.models import DepthEvent
def test_book_snapshot_and_update():
    b=LocalOrderBook(5);b.load_snapshot([['100','2'],['99','1']],[['101','2'],['102','1']],10);assert b.state.mid()==100.5;assert b.apply(DepthEvent(1,11,11,[(100,3)],[]))=='OK';assert b.state.bids[100]==3
