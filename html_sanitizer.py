import html.parser
from urllib.parse import urlparse, urljoin

ALLOWED_TAGS = ['a', 'img', 'div', 'span', 'i', 'b', 'u', 'br', 'hr', 'p', 'video', 'audio', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'ul']
ALLOWED_ATTR = ['src', 'href', 'controls', 'style', 'data-srcset', 'data-src', 'alt', 'title']
BAD_STYLE = ['display', 'border', 'float']

def is_url_absolute(url):
  return not not urlparse(url).netloc

class Sanitizer(html.parser.HTMLParser):
  def __init__(self, link):
    self.sanitized = []
    self.tag_stack = []
    self.link = link
    html.parser.HTMLParser.__init__(self)

  def sanitize(self, htm):
    self.feed(html.unescape(htm))
    self.close()
    return ''.join(self.sanitized)

  def handle_data(self, data):
    self.sanitized.append(data)

  def handle_starttag(self, tag, attrs):
    if tag in ALLOWED_TAGS:
      self.sanitized.append('<'+tag)
      for attr, value in attrs:
        if attr == 'style' and any(i in value.lower() for i in BAD_STYLE):
          continue
        if attr in ALLOWED_ATTR:
          if attr in ('src', 'href') and not is_url_absolute(value):
            value = urljoin(self.link, value)
          try:
            self.sanitized.append(' '+attr+'="'+value.replace('"', '&quot;')+'"')
          except AttributeError:
            self.sanitized.append(' '+attr+'='+repr(value))
      if tag == 'a':
        self.sanitized.append(' target="_new" rel="noreferrer"')
      self.sanitized.append('>')
      self.tag_stack.insert(0, tag)

  def handle_endtag(self, tag):
    if tag in ALLOWED_TAGS:
      try:
        self.tag_stack.remove(tag)
        self.sanitized.append('</'+tag+'>')
      except ValueError:
        pass

  def close(self):
    html.parser.HTMLParser.close(self)
    for tag in self.tag_stack:
      self.sanitized.append('</'+tag+'>')

def sanitize(htm, link):
  return Sanitizer(link).sanitize(htm)
