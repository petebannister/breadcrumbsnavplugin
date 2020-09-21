# -*- coding: utf-8 -*-

import cPickle
import re

from genshi.filters.transform import Transformer

from trac.core import Component, TracError, implements
from trac.config import IntOption, ListOption, Option
from trac.env import IEnvironmentSetupParticipant
from trac.resource import Resource, get_resource_shortname, \
    get_resource_summary, resource_exists
from trac.util.html import html as tag
from trac.web import IRequestFilter
from trac.web.api import ITemplateStreamFilter
from trac.web.chrome import ITemplateProvider, add_stylesheet


class BreadCrumbsSystem(Component):
    """Provider of bread cumbs navigation bar right below Trac metanav."""

    implements(IEnvironmentSetupParticipant, IRequestFilter,
               ITemplateProvider, ITemplateStreamFilter)

    ignore_pattern = Option('breadcrumbs', 'ignore_pattern', None,
                            doc="""Resource names that match this pattern will not be added to
            the breadcrumbs trail.""")

    label = Option('breadcrumbs', 'label', '',
                   doc="""Text label to show before breadcrumb list. If empty,
            'Breadcrumbs:' is used as default.""")

    max_crumbs = IntOption('breadcrumbs', 'max_crumbs', 6,
                           doc="""Indicates maximum number of breadcrumbs to store per user.""")

    supported_paths = ListOption('breadcrumbs', 'paths',
                                 '/wiki/,/ticket/,/milestone/',
                                 doc="""List of URL paths to allow breadcrumb tracking.
            Globs are supported.""")

    compiled_ignore_pattern = None

    # IEnvironmentSetupParticipant methods

    def environment_created(self):
        self._upgrade_db(self.env.get_db_cnx())

    def environment_needs_upgrade(self, db):
        cursor = db.cursor()

        try:
            cursor.execute("""
                SELECT count(*)
                  FROM session_attribute
                 WHERE name = %s
                """, ("breadcrumbs list",)
                           )
            result = cursor.fetchone()
            if int(result[0]):
                return True

            return False
        except:
            db.rollback()
            return True

    def upgrade_environment(self, db):
        self._upgrade_db(db)

    def _upgrade_db(self, db):
        try:
            cursor = db.cursor()
            cursor.execute("""
                DELETE
                  FROM session_attribute
                 WHERE name = %s
                """, ("breadcrumbs list",)
                           )
        except Exception, e:
            db.rollback()
            self.log.error(e, exc_info=True)
            raise TracError(str(e))

    # IRequestFilter methods

    def pre_process_request(self, req, handler):
        return handler

    def post_process_request(self, req, template, data, content_type):
        if self.compiled_ignore_pattern is None and self.ignore_pattern:
            self.compiled_ignore_pattern = re.compile(self.ignore_pattern)

        path = req.path_info
        try:
            if path.count('/') >= 2:
                _, realm, resource_id = path.split('/', 2)

                supported = False

                for pattern in self.supported_paths:
                    if re.match(pattern, path):
                        supported = True
                        break

                # Prevent tracking of prefetched pages as reported for
                #   Mozilla browsers.
                if req.get_header("X-Moz") == "prefetch":
                    supported = False

                if not supported or \
                        (self.compiled_ignore_pattern and
                             self.compiled_ignore_pattern.match(resource_id)):
                    return template, data, content_type

                if '&' in resource_id:
                    resource_id = resource_id[0:resource_id.index('&')]

                sess = req.session
                crumbs = self._get_crumbs(sess)

                current = '/'.join((realm, resource_id))
                if current in crumbs:
                    crumbs.remove(current)
                    crumbs.insert(0, current)
                else:
                    crumbs.insert(0, current)
                    # Keep one over max for providing max length even
                    # when hiding current in first position while viewing it.
                    crumbs = crumbs[0:self.max_crumbs + 1]

                sess['breadcrumbs_list'] = cPickle.dumps(crumbs)
        except:
            self.log.exception("Breadcrumb failed :(")

        return template, data, content_type

    def _get_crumbs(self, sess):
        crumbs = []
        if 'breadcrumbs_list' in sess:
            raw = sess['breadcrumbs_list']
            try:
                crumbs = cPickle.loads(raw.encode('ascii', 'ignore'))
            except:
                del sess['breadcrumbs_list']

        return crumbs

    # ITemplateProvider methods

    def get_htdocs_dirs(self):
        from pkg_resources import resource_filename
        return [('breadcrumbs', resource_filename(__name__, 'htdocs'))]

    def get_templates_dirs(self):
        return []

    # ITemplateStreamFilter method

    def filter_stream(self, req, method, filename, stream, data):
        crumbs = self._get_crumbs(req.session)
        if not crumbs:
            return stream

        add_stylesheet(req, 'breadcrumbs/css/breadcrumbs.css')
        ul = []

        path = req.path_info
        if path.count('/') >= 2:
            realm, resource_id = path.split('/', 2)[1:]
            if '&' in resource_id:
                resource_id = resource_id[0:resource_id.index('&')]
            current = '/'.join((realm, resource_id))
        else:
            current = None

        offset = 0
        if crumbs and crumbs[0] == current:
            offset = 1
        for crumb in crumbs[offset: self.max_crumbs + offset]:
            realm, resource_id = crumb.split('/', 1)
            resource = Resource(realm, resource_id)

            name = get_resource_shortname(self.env, resource)

            if not resource_exists(self.env, resource):
                continue

            title = get_resource_summary(self.env, resource)
            link = req.href(realm, resource_id)

            first = ul == []
            li = tag.li(tag.a(title=title, href=link)(name))
            if first:
                li(class_="first")
            ul.append(li)

        if ul:
            last = ul.pop()
            ul.append(last(class_="last"))
            label = self.label if self.label else "Breadcrumbs:"
            insert = tag.ul(class_="nav", id="breadcrumbs")(tag.li(label), ul)
        else:
            insert = ''

        return stream | Transformer('//div[@id="metanav"]/ul').after(insert)
