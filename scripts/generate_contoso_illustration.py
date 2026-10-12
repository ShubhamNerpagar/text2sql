"""Deterministic offline retail illustration. NOT an official SQLBI Contoso release."""
from pathlib import Path
import random,sqlite3,datetime
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'sample-data'/'contoso'/'contoso_demo.sqlite3'
def main():
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.unlink(missing_ok=True)
    r=random.Random(20261009)
    with sqlite3.connect(OUT) as db:
        db.executescript('''
        CREATE TABLE Customer(CustomerKey INTEGER PRIMARY KEY,CustomerName TEXT NOT NULL,CountryCode TEXT NOT NULL,Segment TEXT NOT NULL);
        CREATE TABLE Product(ProductKey INTEGER PRIMARY KEY,ProductName TEXT NOT NULL,Brand TEXT NOT NULL,Category TEXT NOT NULL,UnitPrice REAL NOT NULL);
        CREATE TABLE Store(StoreKey INTEGER PRIMARY KEY,StoreName TEXT NOT NULL,CountryCode TEXT NOT NULL,Status TEXT NOT NULL);
        CREATE TABLE Orders(OrderKey INTEGER PRIMARY KEY,CustomerKey INTEGER NOT NULL,StoreKey INTEGER NOT NULL,OrderDate TEXT NOT NULL,OrderStatus TEXT NOT NULL,CurrencyCode TEXT NOT NULL);
        CREATE TABLE OrderRows(OrderLineKey INTEGER PRIMARY KEY,OrderKey INTEGER NOT NULL,ProductKey INTEGER NOT NULL,Quantity INTEGER NOT NULL,UnitPrice REAL NOT NULL,Discount REAL NOT NULL);
        CREATE TABLE Sales(SalesKey INTEGER PRIMARY KEY,OrderLineKey INTEGER NOT NULL,OrderKey INTEGER NOT NULL,CustomerKey INTEGER NOT NULL,NetAmount REAL NOT NULL,GrossAmount REAL NOT NULL,OrderDate TEXT NOT NULL);
        CREATE TABLE CurrencyExchange(CurrencyCode TEXT PRIMARY KEY,RateToUSD REAL NOT NULL);
        CREATE TABLE Date(DateKey TEXT PRIMARY KEY,CalendarYear INTEGER NOT NULL,MonthNumber INTEGER NOT NULL,MonthName TEXT NOT NULL);
        ''')
        countries=['DE','IN','US','FR','GB']; currencies={'USD':1,'EUR':1.08,'INR':0.012,'GBP':1.28}
        db.executemany('INSERT INTO Customer VALUES(?,?,?,?)',[(i,f'Customer {i:04d}',r.choice(countries),r.choice(['Retail','Business','Online'])) for i in range(1,1001)])
        db.executemany('INSERT INTO Product VALUES(?,?,?,?,?)',[(i,f'Product {i:03d}',r.choice(['Contoso','Fabrikam','Northwind']),r.choice(['Computers','Phones','Accessories','Home']),round(r.uniform(15,1200),2)) for i in range(1,121)])
        db.executemany('INSERT INTO Store VALUES(?,?,?,?)',[(i,f'Store {i:03d}',r.choice(countries),r.choice(['Open','Open','Open','Closed'])) for i in range(1,41)])
        db.executemany('INSERT INTO CurrencyExchange VALUES (?,?)',currencies.items())
        order_rows=[]; sales=[]; orders=[]; days=set()
        for i in range(1,10001):
            day=(datetime.date(2024,1,1)+datetime.timedelta(days=r.randrange(730))).isoformat(); days.add(day)
            customer=r.randint(1,1000);store=r.randint(1,40);status=r.choices(['Completed','Cancelled','Returned'],[92,4,4])[0]
            orders.append((i,customer,store,day,status,r.choice(list(currencies))))
            for j in range(r.randint(1,3)):
                k=len(order_rows)+1;product=r.randint(1,120);qty=r.randint(1,5);price=round(r.uniform(15,1200),2);discount=round(r.choice([0,.05,.1,.15]) * price * qty,2)
                order_rows.append((k,i,product,qty,price,discount))
                gross=round(price*qty,2); sales.append((k,k,i,customer,round(gross-discount,2),gross,day))
        db.executemany('INSERT INTO Orders VALUES(?,?,?,?,?,?)',orders)
        db.executemany('INSERT INTO OrderRows VALUES(?,?,?,?,?,?)',order_rows)
        db.executemany('INSERT INTO Sales VALUES(?,?,?,?,?,?,?)',sales)
        db.executemany('INSERT INTO Date VALUES(?,?,?,?)',[(d,int(d[:4]),int(d[5:7]),datetime.date.fromisoformat(d).strftime('%B')) for d in sorted(days)])
        db.executescript('CREATE INDEX idx_orders_customer ON Orders(CustomerKey);CREATE INDEX idx_sales_order ON Sales(OrderKey);CREATE INDEX idx_orderrows_order ON OrderRows(OrderKey);')
    print('Illustrative retail dataset:',OUT,'orders=10000','source=locally generated, not SQLBI')
if __name__=='__main__':main()
