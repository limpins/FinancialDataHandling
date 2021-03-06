import requests
import os
import shutil
import pandas
import datetime
import pickle
from pandas_datareader import data as pd_data
from pandas_datareader import base as pd_base
from bs4 import BeautifulSoup


def getNyseTickers():
    filename = "NYSEListedCompanies.xlsx"
    nyse_table = pandas.read_excel(os.path.join(r'D:\Investing\Data', filename))
    OK = (nyse_table.FalseTicker == "-") & (nyse_table.PriceErrors == "-") & (nyse_table.StatementsAvailable == "-")
    return nyse_table.Symbol[OK]


class WebDownloader():
    
    def __init__(self, exchange = "ASX"):
        self.store = Storage(exchange)
        self.WSJ = WSJinternet(exchange)
        self.Yahoo = YahooDataDownloader()

    def saveFinancials(self, tickers):
        scraper = WSJscraper()
        errors = {}
        count = 0
        for period in ['annual', 'interim']:
            for ticker in tickers:
                ticker = ticker.strip()
                count += 1
                if count % 100 == 0:
                    print("Running {} out of {}...".format(count, len(tickers)))
                statements = [StatementWebpage(ticker, 'income', period), 
                              StatementWebpage(ticker, 'balance', period), 
                              StatementWebpage(ticker, 'cashflow', period)]
                financials = Financials(ticker, period)
                saving_financials = True
                for statement in statements:
                    try:
                        statement.html = self.WSJ.load_page(ticker, statement.type, period)
                        if saving_financials:
                            try:
                                financials.statements[statement.type] = scraper.getTables(statement.type, statement.html)
                            except Exception:
                                saving_financials = False
                                errors[ticker] = "Scraper error - " + " ".join([period, statement.type])
                            finally:
                                self.store.save(statement)
                    except Exception:
                        errors[ticker] = "Page load error - " + " ".join([period, statement.type])
                if saving_financials:
                    self.store.save(financials)
        return errors

    def updateFinancials(self, tickers, period):
        if tickers is None:
            tickers = self.all_tickers()
        
        for ticker in tickers:
            
            financials_template = Financials(ticker, period)
            try:
                financials = self.store.load(financials_template)
            except IOError:
                financials = financials_template

            try:
                new_financials = self.WSJ.getFinancials(ticker, period)
            except Exception as e:
                print(e.message + " - problem with " + ticker)
            else:
                financials.merge(new_financials)
                self.store.save(financials)

    def migrateFinancials(self, ticker, period):

        # This method should be only temporary
        # assumes if data is up to date then will be from 2016

        print(" ".join(["Updating",  ticker, period]))
        current = self.store.load(Financials(ticker, period))
        if (current.lastYear() == 2016) & (current.numColumns() > 5):
            print("Data already up to date.")
        elif (current.lastYear() == 2016):
            print("Latest data already available, looking for legacy data")
            legacy = self.createLegacyFinancials(ticker, period)
            legacy.merge(current)
            self.store.save(legacy)
            print("Updated.")
        else:
            print("Downloading new data...")
            try:
                new_financials = self.WSJ.getFinancials(ticker, period)
            except Exception as e:
                print(e.message + " - problem with " + ticker)
            else:
                current.merge(new_financials)
                self.store.save(current)
                print("Updated.")


    def migrateAndUpdateAllFinancials(self, tickers = None):

        if tickers is None:
            tickers = self.all_tickers()

        errors = []

        for ticker in tickers:
            for period in ["annual", "interim"]:
                try:
                    self.migrateFinancials(ticker, period)
                except Exception as e:
                    error_message = " - ".join([e.message, ticker, period])
                    print(error_message)
                    errors.append(error_message)
            print("-" * 20)

        return errors



    def createLegacyFinancials(self, ticker, period):
        
        # This method should only be temporary until all stocks have 
        # data stored as Financials objects.
        financials = Financials(ticker, period)
        
        if period == "annual":
            path = self.store.annualFinancials(financials)
        elif period == "interim":
            path = self.store.interimFinancials(financials)
        else:
            raise ValueError("period must be 'annual' or 'interim'")

        financials_dict = {}
        financials_dict["ticker"] = ticker
        financials_dict["period"] = period
        statements = {}

        income_done = False
        balance_done = False
        cashflow_done = False

        # Look for pandas pickle.
        income_pickle = os.path.join(path, "income.pkl")
        if os.path.exists(income_pickle):
            statements["income"] = {}
            with open(income_pickle, 'rb') as file:
                statements["income"]["income"] = pickle.load(file)
            income_done = True
        
        assets_pickle = os.path.join(path, "assets.pkl")
        liab_pickle = os.path.join(path, "liabilities.pkl")
        if os.path.exists(assets_pickle) & os.path.exists(liab_pickle):
            statements["balance"] = {}
            with open(assets_pickle, 'rb') as file:
                statements["balance"]["assets"] = pickle.load(file)
            with open(liab_pickle, 'rb') as file:
                statements["balance"]["liabilities"] = pickle.load(file)
            balance_done = True

        operating_pickle = os.path.join(path, "operating.pkl")
        financing_pickle = os.path.join(path, "financing.pkl")
        investing_pickle = os.path.join(path, "investing.pkl")
        if os.path.exists(operating_pickle) & os.path.exists(financing_pickle) & os.path.exists(investing_pickle):
            statements["cashflow"] = {}
            with open(operating_pickle, 'rb') as file:
                statements["cashflow"]["operating"] = pickle.load(file)
            with open(financing_pickle, 'rb') as file:
                statements["cashflow"]["financing"] = pickle.load(file)
            with open(investing_pickle, 'rb') as file:
                statements["cashflow"]["investing"] = pickle.load(file)
            cashflow_done = True

        # If pandas pickle not loaded, look for html.
        scraper = WSJscraper()
        income_html = os.path.join(path, ticker + "income.html")
        balance_html = os.path.join(path, ticker + "balance.html")
        cashflow_html = os.path.join(path, ticker + "cashflow.html")
        if (not income_done) & os.path.exists(income_html):
            try:
                with open(income_html, 'r') as file:
                    page = file.read()
                    statements["income"] = scraper.getTables("income", page)
            except MissingStatementEntryError:
                pass
        if (not balance_done) & os.path.exists(balance_html):
            try:
                with open(balance_html, 'r') as file:
                    page = file.read()
                    statements["balance"] = scraper.getTables("balance", page)
            except MissingStatementEntryError:
                pass
        if (not cashflow_done) & os.path.exists(cashflow_html):
            try:
                with open(cashflow_html, 'r') as file:
                    page = file.read()
                    statements["cashflow"] = scraper.getTables("cashflow", page)
            except MissingStatementEntryError:
                pass

        financials_dict["statements"] = statements
        financials.from_dict(financials_dict)
        return financials


    def updatePriceHistory(self, tickers = None, start = None):
        if tickers is None:
            tickers = self.all_tickers()

        for ticker in tickers:
            price_history = PriceHistory(ticker)
            try:
                price_history.prices = self.Yahoo.priceHistory(ticker, start)
            except Exception as e:
                print(e.message + " - problem getting " + ticker)
            else:
                self.store.save(price_history)

    def priceHistory(self, ticker):
        price_history = PriceHistory(ticker)
        return self.store.load(price_history)

    def currentPrice(self, ticker):
        return self.Yahoo.currentPrice(ticker)


    def all_tickers(self):
        return [ticker for ticker in os.listdir(self.store.data) if "." not in ticker]


class WSJinternet():

    def __init__(self, exchange = "ASX"):
        if exchange is "ASX":
            self.page_root = "http://quotes.wsj.com/AU/XASX/"
        elif exchange is "NYSE":
            self.page_root = "http://quotes.wsj.com/"
        self.summary_pages = {"overview" : "", 
                              "financials" : "/financials"}
        self.statement_pages = {"income" : "/financials/<period>/income-statement", 
                                "balance" : "/financials/<period>/balance-sheet", 
                                "cashflow" : "/financials/<period>/cash-flow"}
        self.scraper = WSJscraper()
     
        
    def getFinancials(self, ticker, period):
        financials = Financials(ticker, period)

        for sheet in self.statement_pages:
            html = self.load_page(ticker, sheet, period)
            financials.statements[sheet] = self.scraper.getTables(sheet, html)

        return financials

    def get_address(self, ticker, sheet, period = "annual"):
        if period not in ["annual", "quarter", "interim"]:
            raise ValueError("Should be 'annual', 'interim' or 'quarter'")
        if period == "interim":
            period = "quarter"
        address = self.page_root + ticker + self.statement_pages[sheet]
        return  address.replace("<period>", period)

    def load_page(self, ticker, sheet, period):
        try:
            page = requests.get(self.get_address(ticker, sheet, period))
        except requests.HTTPError:
            print("Problem downloading: " + ticker + " " + sheet)
        return page.content


class WSJlocal(WSJinternet):

    def __init__(self, exchange = "ASX"):
        self.page_root = "D:\\Investing\\Data\\" + exchange + "\\"
        self.statement_pages = {"income"    :   "\\Financials\\<period>\\<ticker>income.html", 
                                "balance"   :   "\\Financials\\<period>\\<ticker>balance.html",
                                "cashflow"   :   "\\Financials\\<period>\\<ticker>cashflow.html"}
        self.scraper = WSJscraper()

    def load_page(self, ticker, sheet, period):
        location = self.page_root + ticker + self.statement_pages[sheet]
        location = location.replace("<ticker>", ticker)
        location = location.replace("<period>", period)
        try:
            with open(location, 'r') as file:
                page = file.read()
        except:
            print("Problem loading: " + location)
        return page
            

class WSJscraper():

    def __init__(self):
        '''
        statements defines the search terms to look for in each html page to find the table.
        i.e. reading from left to right: in 'income' html, to find 'income' table look for 'Sales/Revenue'.
        '''
        #                   PAGE          TABLE           CONTAINS
        self.statements = {"income"   : {"income"      : "Sales/Revenue"}, 
                           "balance"  : {"assets"      : "Cash & Short Term Investments", 
                                         "liabilities" : "ST Debt & Current Portion LT Debt"}, 
                           "cashflow" : {"operating"   : "Net Operating Cash Flow", 
                                         "investing"   : "Capital Expenditures", 
                                         "financing"   : "Cash Dividends Paid - Total"}}


    def load_overview(self, ticker, store):
        overview = store.html(ticker, "overview")
        with open(overview, 'r') as page:
            self.overview = BeautifulSoup(page, "lxml")

    def keyStockData(self):
        key_data_table = self.overview.find(id = "cr_keystock_drawer")
        key_data_table = key_data_table.find("div")
        table_entries = key_data_table.find_all("li")
        labels = []
        values = []
        for entry in table_entries:
            label = str(entry.h5.text)
            labels.append(label)
            
            # Clean up tag string content. Note some tags may have leading white space
            # before a child tag and so all text is retrieved (ignoring children) and
            # combined, before removing unwanted characters.
            value = ''.join(entry.span.find_all(text = True, recursive = False))
            value = value.strip()
            value = value.replace("%", "")
            value = value.replace("M", "")
            
            try:
                value = float(value)
            except ValueError:
                value = str(value)

            values.append(value)
        return dict(zip(labels, values))

    def getTables(self, sheet, html):
        page = self.statements[sheet]
        scraped_tables = {}
        for table in page:
            search_term = page[table]
            scraped_tables[table] = self.read_statement_table(html, search_term)
        return scraped_tables

    def read_statement_table(self, html, contains):
        try:
            table = pandas.read_html(html, match = contains, index_col = 0)[0]
        except ValueError as E:
            raise MissingStatementEntryError(E.message)
        headings = table.columns.tolist()
        # Delete empty columns after final year
        # First column after final year is trend column
        trend_ix = ["trend" in heading for heading in headings].index(True)
        for heading in headings[trend_ix:]:
            del table[heading]
        # Delete rows starting with 'nan'
        non_nans = [not isinstance(row_label, float) for row_label in table.index]
        table = table.loc[non_nans]
        self.check_years(table.columns.tolist())
        return table

    def check_years(self, years):
        if not all(['20' in year for year in years]):
            raise InsufficientDataError("Empty report years")


class CMCscraper():

    def __init__(self, store):
        self.store = store
        self.root_page = "https://www.cmcmarketsstockbroking.com.au"
        self.login_url = self.root_page + "/login.aspx"
        self.payload = {"logonAccount" : "markhocky", 
                        "logonPassword" : "X", 
                        "source" : "cmcpublic", 
                        "referrer" : self.root_page + "/default.aspx?"}
        self.session = None


    def loginSession(self):
        password = input("Enter password for " + self.payload["logonAccount"])
        self.payload["logonPassword"] = password
        self.session = requests.Session()
        self.session.post(self.login_url, data = self.payload)

    def researchPage(self, ticker):
        research_page = self.root_page + "/net/ui/Research/Research.aspx?asxcode=" + ticker + "&view=historical"
        return research_page

    def download_historicals(self, tickers):
        for ticker in tickers:
            try:
                per_share, historical = self.historicalFigures(ticker)
            except Exception:
                print("No results for " + ticker)
            else:
                self.store.save(historical)
                self.store.save(per_share)


    def historicalFigures(self, ticker):
        if self.session is None:
            self.loginSession()

        page = self.session.get(self.researchPage(ticker))
        soup = BeautifulSoup(page.text, "lxml")
        per_share_stats = pandas.read_html(str(soup.find_all("table")), match = "PER SHARE")[-1]
        per_share = CMCpershare(ticker)
        per_share.summary = self.cleanTable(per_share_stats)
        historical_financials = pandas.read_html(str(soup.find_all("table")), match = "HISTORICAL")[-1]
        historical = CMChistoricals(ticker)
        historical.summary = self.cleanTable(historical_financials)
        return (per_share, historical)


    def cleanTable(self, table):
        table_name = table.columns[0]
        dates = table.iloc[1][1:].tolist()
        dates.insert(0, table_name)
        table.columns = dates
        table = table.ix[2:]

        row_labels = table.iloc[:, 0]
        row_labels = [row.replace("\\r\\n", "") for row in row_labels]
        row_labels = [row.replace("\\xa0", " ") for row in row_labels]

        table.index = row_labels
        table = table.iloc[:, 1:]
        table = table.apply(pandas.to_numeric, errors = 'coerce')
        return table


class InsufficientDataError(IOError):
    pass

class MissingStatementEntryError(IOError):
    pass

