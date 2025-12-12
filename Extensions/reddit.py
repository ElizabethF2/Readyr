import sessen, os, urllib.parse, re, time, json, datetime

MAX_CACHE_SIZE = 3000
IMG_EXTS = ['jpg', 'jpeg', 'gif', 'png', 'webp']

logger = sessen.getLogger(name='Reddit')

try:
  with open('reddit_config.json', 'r') as f:
    config = json.load(f)
except FileNotFoundError:
  config = {}

def get_media_htm(child, max_img_width):
  img_src = None
  url = child['data']['url']
  if any((url.lower().endswith('.'+e) for e in IMG_EXTS)):
    img_src = url
  elif url.lower().endswith('.gifv'):
    img_src = url[:-1]
  #elif 'gfycat.com/' in url.lower():
  #  img_src = url+'.gif'
  elif 'imgur.com' in url:
    ps = urllib.parse.urlparse(url).path.split('/')
    if len(ps) > 1 and ps[1] != 'a':
      img_src = 'https://i.imgur.com/'+ps[1]+'.png'

  if img_src and max_img_width:
    return '<img src="'+img_src+'" style="max-width: ' + max_img_width + ';">'
  elif img_src:
    return '<img src="'+img_src+'" style="max-height: 80vh;">'

_spam_detector = None

def _web_request(method, url, headers, data = None, ssl_verify = True):
  return sessen.webrequest(
    method,
    url,
    headers = headers,
    data = data,
    ssl_verify = ssl_verify,
    timeout = _spam_detector.DOWNLOAD_TIMEOUT,
  ).data

def _dprint(*msgs):
  sessen.ExtensionProxy('console').print(*map(str, msgs))

def is_spam(child):
  global _spam_detector

  post = child['data']
  title = post['title']

  blacklist = config.get('blacklist') or []
  title_blacklist = config.get('title_blacklist') or []

  if any((i in title.lower() for i in blacklist)):
    return True

  if any((re.search(rx, title) for rx in title_blacklist)):
    return True

  try:
    if any((i in post['selftext'].lower() for i in blacklist)):
      return True
  except KeyError:
    pass

  if any((i in post['url'] for i in blacklist)):
    return True

  if post['author'] in blacklist:
    return True

  try:
    for parent in child['data']['crosspost_parent_list']:
      if any((i in parent['subreddit_name_prefixed'] for i in blacklist)):
        return True
  except KeyError:
    pass

  if child['data']['removed_by_category']:
    return True

  if _spam_detector is None:
    if detector := config.get('spam_detector_lib'):
      detector = sessen.load_subextension(os.path.abspath(detector))
      detector.web_request = _web_request
      detector.dprint = _dprint
      detector.SERIALIZE_USER_CACHE = config.get('serialize_user_cache', True)
      detector.SERIALIZED_USER_CACHE_PATH = config.get(
        'serialized_user_cache_path', 'spam_detector_user_cache.json'
      )
      detector.MAX_SERIALIZED_USER_CACHE = int(
        config.get('max_serialized_user_cache',
                   detector.MAX_SERIALIZED_USER_CACHE)
      )
      _spam_detector = detector
      return _spam_detector.check_post(post)
  else:
    return _spam_detector.check_post(post)

  return False


def str2bool(s):
  try:
    return bool(float(s))
  except ValueError:
    if s[0].lower() in ('y', 't'):
      return True
  return False


_AUTHOR_CACHE = {}

class Feed(object):
  id = 'reddit'

  def get(self, args):
    # Get the urls
    url = args['url'][0].replace(' ', '+')
    if url.endswith('/'):
      url = url[:-1]

    api_url = url.replace('search/?', 'search.json?')
    if len(api_url.split('/')) == 5:
      api_url += '/hot'
    if '.json' not in api_url:
      if '?' in api_url:
        api_url = api_url.replace('?', '.json?')
      else:
        api_url = api_url + '.json'

    # Query the api
    js = sessen.webrequest('GET', api_url).json()

    # Setup args
    has_max_score = 'max_score' in args
    if has_max_score:
      max_score = int(args['max_score'][0])
    
    has_min_score = 'min_score' in args
    if has_min_score:
      min_score = int(args['min_score'][0])

    delay = 0
    if 'delay' in args:
      res = re.search(r'((?P<days>\d+)[D|d])?.*?((?P<hours>\d+)[H|h])?', args['delay'][0])
      delay += int(res.group('days') or 0) * 24 * 60 * 60
      delay += int(res.group('hours') or 0) * 60 * 60

    exclude = args.get('exclude') or []

    # Generate the feed title
    if 'title' in args:
      title = args['title'][0]
    else:
      title = url
      sp = urllib.parse.urlparse(url).path.split('/')[1:]
      if len(sp) >= 2 and sp[0].lower() in ('r', 'u', 'user'):
        title = sp[1]
        if len(sp) >= 3:
          suffix = {
            'new': 'Newest Submissions',
            'rising': 'Rising Submissions',
            'controversial': 'Controversial Submissions',
            'top': 'Top Submissions',
            'gilded': 'Gilded Posts'
          }.get(sp[2])
          if suffix:
            title += ' - ' + suffix

    feed = {'title': title, 'link': url, 'items': []}

    # Handle subs that have gone (hopefully temporarily) private
    if js.get('error') == 403 and js.get('reason') == 'private':
      now = datetime.datetime.now()
      feed['items'].append({
        'title': 'Feed has gone private!',
        'link': url,
        'guid': 'private:'+str((now.year, now.month))+':'+url,
        'description': 'This item was automatically generated.'
      })
      return feed

    # Add children to feed
    max_img_width = args['max_img_width'][0] if 'max_img_width' in args else None

    

    for child in reversed(js['data']['children']):
      post = child['data']
      title = child['data']['title']
      author = post['author']
      id = post['id']

      if has_max_score and child['data']['score'] > max_score:
        continue

      if has_min_score and child['data']['score'] < min_score:
        continue

      if any((e in title for e in exclude)):
        continue

      if (time.time() - child['data']['created_utc']) < delay:
        if id not in _AUTHOR_CACHE:
          _AUTHOR_CACHE[id] = author
        continue

      if is_spam(child):
        continue

      try:
        author = _AUTHOR_CACHE.pop(id)
      except KeyError:
        pass

      description = ['By <a href="https://reddit.com/u/'+author+'">u/'+author+'</a>']
      if 'selftext_html' in child['data'] and child['data']['selftext_html']:
        description.append(child['data']['selftext_html'])

      media_htm = get_media_htm(child, max_img_width)
      thumbnail = child['data']['thumbnail']
      if media_htm:
        description.append(media_htm)
      elif thumbnail not in ('self', 'default', 'nsfw', 'spoiler', '', None):
        description.append('<img src="'+thumbnail+'">')
      elif thumbnail == 'nsfw':
        description.append('<br>[NSFW thumbnail hidden]')
      elif thumbnail == 'spoiler':
        description.append('<br>[spoiler thumbnail hidden]')

      flair = child['data']['link_flair_text']
      if flair:
        title = '[' + flair + '] ' + title

      feed['items'].append({
        'title': title,
        'link': 'https://redd.it/'+child['data']['id'],
        'guid': child['data']['id'],
        'description': '<br><br>'.join(description),
        'pubdate': child['data']['created_utc'],
      })

    return feed

feeds = [Feed()]
