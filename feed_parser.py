# In a perfect world, feeds would never have malformed XML
# Unfortunately, we do not live in a perfect world
# Which is why I'm using regex rather than an XML parser

import re, mimetypes

def _get_raw_title(xml):
  try:
    return re.search('(?is)<\s*title.*?>(.+?)</\s*title\s*>', xml).group(1)
  except (AttributeError, IndexError):
    pass
  try:
    return re.search('(?is)<\s*media:title.*?>(.+?)</\s*media:title\s*>', xml).group(1)
  except (AttributeError, IndexError):
    pass
  return 'No Title'

def _get_title(xml):
  title = _get_raw_title(xml)
  if title.startswith('<![CDATA[') and title.endswith(']]>'):
    title = title[9:-3]
  return title

def _get_link(xml):
  try:
    return re.search('(?is)<\s*link\s*>(.*?)</\s*link\s*>', xml).group(1)
  except (AttributeError, IndexError):
    pass
  xml = re.sub('(?is)<\s*link.+?rel\s*=\s*.self.+?>', '', xml)
  s = re.search('(?is)<\s*link.+?href\s*=\s*("(.+?)"|\'(.+?)\')', xml)
  try:
    return s.group(2) or s.group(3)
  except (AttributeError, IndexError):
    pass
  return ''

def _get_raw_description(xml):
  try:
    return re.search('(?is)<\s*content:encoded.*?>(.*?)</\s*content:encoded\s*>', xml).group(1)
  except (AttributeError, IndexError):
    pass
  try:
    return re.search('(?is)<\s*media:description.*?>(.*?)</\s*media:description\s*>', xml).group(1)
  except (AttributeError, IndexError):
    pass
  try:
    return re.search('(?is)<\s*description\s*>(.*?)</\s*description\s*>', xml).group(1)
  except (AttributeError, IndexError):
    pass
  try:
    return re.search('(?is)<\s*content\s.*?>(.*?)</\s*content\s*>', xml).group(1)
  except (AttributeError, IndexError):
    pass
  return ''

def _get_description_with_extensions(xml):
  description = _get_raw_description(xml)
  if description.startswith('<![CDATA[') and description.endswith(']]>'):
    description = description[9:-3]
  s = re.search('(?is)<\s*enclosure\s.*?url\s*=\s*("(.+?)"|\'(.+?)\')', xml)
  try:
    url = s.group(2) or s.group(3)
    type2tag = {'image': 'img', 'audio': 'audio', 'video': 'video'}
    s = re.search('(?is)<\s*enclosure\s.*?type\s*=\s*["\'](.+?)/', xml)
    try:
      tag = type2tag[s.group(1)]
    except (AttributeError, IndexError, KeyError):
      try:
        tag = type2tag[mimetypes.guess_type(url)[0].split('/')[0]]
      except (AttributeError, IndexError, KeyError):
        tag = 'img'
    description = '<'+tag+' controls src="'+url+'" /><br><br>' + description
  except (AttributeError, IndexError):
    pass
  s = re.search('(?is)<\s*media:thumbnail.+?url\s*=\s*"(.+?)"', xml)
  try:
    url = s.group(1)
    description = '<img src="'+url+'" /><br><br>' + description
  except AttributeError:
    pass
  return description

def _get_guid(xml):
  try:
    return re.search('(?is)<\s*guid\s*>(.*?)</\s*guid\s*>', xml).group(1)
  except (AttributeError, IndexError):
    pass
  try:
    return re.search('(?is)<\s*id\s*>(.*?)</\s*id\s*>', xml).group(1)
  except (AttributeError, IndexError):
    return None

def parse(xml):
  try:
    xml = xml.decode()
  except AttributeError:
    pass
  items = re.findall('(?is)<\s*item.*?>.*?</\s*item\s*>', xml)
  items.extend(re.findall('(?is)<\s*entry.*?>.*?</\s*entry\s*>', xml))
  header_xml = re.sub('(?is)<\s*image.+?</\s*image.*?>', '', xml)
  for item in items:
    header_xml = header_xml.replace(item, '')
  title = _get_title(header_xml)
  link = _get_link(header_xml)
  feed = {'title': title, 'link': link, 'items': []}
  for item in items:
    title = _get_title(item)
    link = _get_link(item)
    description = _get_description_with_extensions(item)
    guid = _get_guid(item) or link
    i = {'title': title, 'link': link, 'description': description, 'guid': guid}
    s = re.search('(?is)<\s*pubdate\s*>(.*?)</\s*pubdate\s*>', item)
    try:
      i['pubdate'] = s.group(1)
    except (AttributeError, IndexError):
      s = re.search('(?is)<\s*updated\s*>(.*?)</\s*updated\s*>', item)
      try:
        i['updated'] = s.group(1)
      except (AttributeError, IndexError):
        pass
    feed['items'].append(i)
  return feed
