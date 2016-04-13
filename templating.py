import jinja2

def get_by_tag(itemlist, required):
    for item in itemlist:
        if 'tags' in item:
            if required in item['tags']:
                return item

def expand_string(string, namespace={}, this=None):
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.globals.update({'namespace': namespace, 'this': this, 'get_by_tag': get_by_tag})
    return_value = env.from_string(string).render()
    if return_value is None:
        raise ConfigException("Failed to parse template string '%s'" % string)
    return return_value

