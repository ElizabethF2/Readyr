import hashlib, time, threading, email.utils, html, os, json, urllib.parse
import sessen, multithreaded_sqlite
import feed_parser, html_sanitizer

MAX_ITEMS_PER_PAGE = 100
NUMBER_OF_FAILED_UPDATES_TO_LOG_AT = 3

app_html = sessen.get_file('app.htm')
config = json.loads(sessen.get_file('config.json'))

database = multithreaded_sqlite.connect(os.path.join(os.path.dirname(__file__), 'subscriptions.db'), timeout=60)
persistent = sessen.PersistentDatastore()
dstore = sessen.ExtensionDatastore()

def init_db(db):
  db.execute('create table if not exists subscriptions (title TEXT, link TEXT, url TEXT PRIMARY KEY, category TEXT)')
  db.execute('create table if not exists items (guid BLOB PRIMARY KEY, title TEXT, link TEXT, description TEXT, pubdate REAL, read INTEGER, subscription INTEGER)')
database.run(init_db)

logger = sessen.getLogger()

subextension_feeds = {}
for e in sessen.listdir('Extensions'):
  e = sessen.load_subextension(os.path.join('Extensions',e))
  for f in e.feeds:
    subextension_feeds[f.id] = f

def sha1(s):
  try:
    return hashlib.sha1(s).digest()
  except TypeError:
    return hashlib.sha1(s.encode()).digest()

def make_subscription_dict(tup):
  keys = ('rowid', 'title', 'link', 'url', 'category')
  return {keys[i]:tup[i] for i in range(len(tup))}

def make_item_dict(tup):
  keys = ('guid', 'title', 'link', 'description', 'pubdate', 'read', 'subscription_rowid')
  return {keys[i]:(tup[i] if keys[i]!='guid' else tup[i].hex()) for i in range(len(tup))}

def get_feed(url):
  p = urllib.parse.urlparse(url)
  if p.path in subextension_feeds:
    feed = subextension_feeds[p.path].get(urllib.parse.parse_qs(p.query))
  else:
    r = sessen.webrequest('GET', url)
    feed = feed_parser.parse(r.text())
  feed['url'] = url
  return feed

def update_feed_items(subscription, feed):
  items = []
  for item in feed['items']:
    link = html.unescape(item['link'])
    title = html_sanitizer.sanitize(item['title'], link)
    guid = sha1(sha1(subscription['url'])+sha1(item['guid']))
    description = html_sanitizer.sanitize(item['description'], link)
    try:
      pubdate = time.mktime(email.utils.parsedate(item['pubdate']))
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
      try:
        pubdate = time.mktime(time.strptime(item['updated'], '%Y-%m-%dT%H:%M:%S%z'))
      except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
        if 'pubdate' in item and type(item['pubdate']) is float:
          pubdate = item['pubdate']
        elif 'pubdate' in item and type(item['pubdate']) is int:
          pubdate = float(item['pubdate'])
        else:
          pubdate = time.time()
    read = False
    subscription_rowid = subscription['rowid']
    items.append((guid, item['title'], link, description, pubdate, read, subscription_rowid))
  def f(db):
    for item in items:
      db.execute('INSERT OR IGNORE INTO items VALUES (?,?,?,?,?,?,?)', item)
    db.commit()
  database.run(f)

_failed_update_count = {}
def update_feed(subscription):
  try:
    url = subscription['url']
    feed = get_feed(url)
    update_feed_items(subscription, feed)
    _failed_update_count.pop(url, None)
  except Exception as ex:
    import traceback
    logger.info('dbg failure ' + url + time.strftime(' %c ') + traceback.format_exc())
    count = _failed_update_count.get(url, 0) + 1
    _failed_update_count[url] = count
    if count == NUMBER_OF_FAILED_UPDATES_TO_LOG_AT:
      try:
        import traceback
        logger.error('Failed to update feed ' + str(count) + ' time(s) - ' + subscription['url'] + ' - ' + traceback.format_exc())
      except:
        logger.error('Failed to update feed ' + str(count) + ' time(s) - ' + subscription['url'] + ' - ' + repr(ex))

def update_feeds():
  def f(db):
    cur = db.execute('SELECT ROWID,* FROM subscriptions')
    return cur.fetchall()
  for subscription in map(make_subscription_dict, database.run(f)):
    time.sleep(30)
    update_feed(subscription)

def update_feeds_worker():
  if 'Microsoft' in sessen.webrequest('GET', 'http://www.spyber.com').text():
    logger.info('HACK HACK HACK Stopping update_feeds_worker')
    return

  while True:
    time.sleep(80*60)
    update_feeds()

threading.Thread(target=update_feeds_worker, daemon=True).start()

@sessen.bind('GET', '/?$')
def main_page(connection):
  connection.send_html(app_html)

def requires_login(func):
  def wrapper(connection, *args, **kwargs):
    try:
      logged_in = persistent.get(connection, 'logged_in')
    except KeyError:
      logged_in = False
    if logged_in:
        return func(connection, *args, **kwargs)
    connection.send_json({'error': 'Unauthenticated'})
  return wrapper

@sessen.bind('POST', '/subscriptions$')
@requires_login
def add_subscription(connection):
  try:
    error = 'Invalid input'
    j = connection.receive_json()
    url = j['url']
    error = 'Unable to load feed'
    feed = get_feed(url)
    error = 'Feed missing title'
    title = feed['title']
    error = 'Feed missing link'
    link = feed['link']
    category = j.get('category') or 'Misc'
    subscription = {'title': title, 'url': url, 'link': link, 'category': category, 'pages': 0, 'unread': 0, 'read': 0}
    error = None
  except Exception as ex:
    try:
      import traceback
      logger.error('Failed to add subscription - ' + url + ' - ' + traceback.format_exc())
    except:
      logger.error('Failed to add subscription - ' + url + ' - ' + repr(ex))
  if not error:
    def f(db):
      cur = db.execute('INSERT OR REPLACE INTO subscriptions VALUES (?,?,?,?)', (title, link, url, category))
      return cur.lastrowid
    subscription['rowid'] = database.run(f)
    update_feed_items(subscription, feed)
  connection.send_json({'error':error})

@sessen.bind('GET', '/subscriptions$')
@requires_login
def get_subscriptions(connection):
  def f(db):
    cur = db.execute('SELECT ROWID, * FROM subscriptions')
    subscriptions = {i[0]:make_subscription_dict(i) for i in cur.fetchall()}
    cur = db.execute('SELECT subscription, read, count(subscription) FROM items GROUP BY subscription,read')
    res = cur.fetchall()
    for rowid, read, count in res:
      subscriptions[rowid]['read' if read else 'unread'] = count
      subscriptions[rowid]['read_pages' if read else 'unread_pages'] = count//MAX_ITEMS_PER_PAGE
    return subscriptions
  subscriptions = {sha1(i['url']).hex():i for i in database.run(f).values()}
  connection.send_json(subscriptions)

_url_hash_cache = {}
def get_sub_by_url_hash(url_hash):
  if url_hash not in _url_hash_cache:
    def f(db):
      _url_hash_cache.clear()
      cur = db.execute('SELECT ROWID, * FROM subscriptions')
      for row in cur:
        sub = make_subscription_dict(row)
        _url_hash_cache[sha1(sub['url']).hex()] = sub
    database.run(f)
  return _url_hash_cache.get(url_hash)

@sessen.bind('DELETE', '/subscriptions/(?P<url_hash>.+)')
@requires_login
def delete_subscription(connection):
  sub = get_sub_by_url_hash(connection.args['url_hash'])
  if sub:
    def f(db):
      old_level = db.isolation_level
      try:
        db.isolation_level = 'EXCLUSIVE'
        cur = db.execute('BEGIN EXCLUSIVE')
        cur.execute('DELETE FROM subscriptions WHERE ROWID=(?) and url=(?)', (sub['rowid'], sub['url']))
        if cur.rowcount == 1:
          cur.execute('DELETE FROM items WHERE subscription=(?)', (sub['rowid'],))
      except Exception as ex:
        db.rollback()
        raise ex
      finally:
        cur.execute('COMMIT')
        db.isolation_level = old_level
        cur.close()
    database.run(f)
  connection.send_json({})

@requires_login
def get_page(connection, read):
  sub = get_sub_by_url_hash(connection.args['url_hash'])
  try:
    page_num = int(connection.args['page_num'])
  except ValueError:
    return connection.send_json({'error': 'Invalid page number'})
  offset = page_num * MAX_ITEMS_PER_PAGE
  if sub:
    subscription_rowid = sub['rowid']
    def f(db):
      cur = db.execute('SELECT * FROM items WHERE subscription=(?) AND read=(?) ORDER BY pubdate ASC LIMIT (?) OFFSET (?)',
                       (subscription_rowid, read, MAX_ITEMS_PER_PAGE, offset))
      return [make_item_dict(i) for i in cur.fetchall()]
    result = {'items': database.run(f)}
    connection.send_json({'result': result})
  else:
    connection.send_json({'error': 'Invalid feed'})

sessen.bind('GET',
            '/subscriptions/(?P<url_hash>.+?)/read/(?P<page_num>\d+)$',
            lambda connection: get_page(connection, True))

sessen.bind('GET',
            '/subscriptions/(?P<url_hash>.+?)/unread/(?P<page_num>\d+)$',
            lambda connection: get_page(connection, False))

@sessen.bind('PUT', '/items$')
@requires_login
def update_items(connection):
  j = connection.receive_json()
  try:
    items = [(bytes.fromhex(guid), bool(data['read'])) for guid, data in j.items()]
  except (ValueError, KeyError):
    return connection.send_json({'error': 'Invalid items'})
  def f(db):
    for guid, read in items:
      db.execute('UPDATE items SET read=(?) WHERE guid=(?)', (read, guid))
    db.commit()
  database.run(f)
  connection.send_json({'error': None})

@sessen.bind('PUT', '/subscriptions/(?P<url_hash>.+?)$')
@requires_login
def update_subscription(connection):
  sub = get_sub_by_url_hash(connection.args['url_hash'])
  if sub:
    j = connection.receive_json()
    category = j.get('category')
    if not category:
      return connection.send_json({'error': 'Missing category'})
    def f(db):
      db.execute('UPDATE subscriptions SET category=(?) WHERE url=(?)', (category, sub['url']))
    database.run(f)
  else:
    return connection.send_json({'error': 'Invalid subscription'})
  connection.send_json({'error': None})

@sessen.bind('POST', '/refresh_subscription/(?P<url_hash>.+?)$')
@requires_login
def refresh_subscription(connection):
  sub = get_sub_by_url_hash(connection.args['url_hash'])
  if sub:
    update_feed(sub)
    connection.send_json({'error': None})
  else:
    return connection.send_json({'error': 'Invalid subscription'})

@sessen.bind('POST', '/login$')
def login(connection):
  try:
    password = connection.receive_json()['password']
    if password == dstore['password']:
      persistent.set(connection, 'logged_in', True)
      connection.send_json({'error':None})
      return
  except:
    pass
  connection.send_json({'error': 'Invalid Login'})

@sessen.bind('POST', '/logout$')
def logout(connection):
  persistent.delete_all(connection)
  connection.send_json({'error':None})
