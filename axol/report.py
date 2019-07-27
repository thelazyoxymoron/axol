#!/usr/bin/env python3
import argparse
import sys
import logging
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from itertools import islice
from pathlib import Path
from pprint import pprint
from subprocess import check_call, check_output
from typing import (Any, Dict, Iterator, List, NamedTuple, Optional, Sequence,
    Tuple, Type, Union)

import dominate
import dominate.tags as T
from dominate.util import raw, text
from kython import classproperty, cproperty, flatten

from axol.common import logger
from axol.storage import Changes, RepoHandle, get_digest, get_result_type
from axol.trait import AbsTrait, pull
from axol.traits import ForReach, ForSpinboard, ForTentacle, ignore_result
from config import OUTPUTS, ignored_reddit


# TODO need some sort of starting_from??
# TODO I guess just use datetime?


Htmlish = Union[str, T.dom_tag]

# TODO use Genetic[T]??

# TODO hmm. maybe calling base class method pulls automatically??
class FormatTrait(AbsTrait):
    @classmethod
    def format(trait, obj, *args, **kwargs) -> Htmlish:
        raise NotImplementedError
format_result = pull(FormatTrait.format)


def isempty(s) -> bool:
    if s is None:
        return True
    if len(s.strip()) == 0:
        return True
    return False

# def fdate(d: datetime) -> str:
#     return d.strftime("%Y-%m-%d %H:%M")

def fdate(d: datetime) -> str:
    return d.strftime('%a %d %b %Y %H:%M')



# TODO not sure if should inherit from trait... it's more of an impl..
class SpinboardFormat(ForSpinboard, FormatTrait):
    @staticmethod
    def plink(user=None, tag=None) -> str:
        ll = f'https://pinboard.in'
        if user is not None:
            ll += f'/u:{user}'
        if tag is not None:
            ll += f'/t:{tag}'
        return ll

    @classmethod
    def tag_link(cls, tag: str, user=None):
        ll = cls.plink(tag=tag, user=user)
        return T.a(f'#{tag}', href=ll, cls='tag')

    @classmethod
    def user_link(cls, user: str):
        ll = cls.plink(user=user)
        return T.a(user, href=ll, cls='user')

    # TODO default formatter?
    # TODO Self ?? maybe it should be metaclass or something?
    @classmethod
    def format(trait, obj, *args, **kwargs) -> Htmlish:
        # TODO would be nice to have spinboard imported here for type checking..
        res = T.div(cls='pinboard')
        res.add(T.a(obj.title, href=obj.link))
        res.add(T.br())
        if not isempty(obj.description):
            res.add(obj.description)
            res.add(T.br())
        # res.add('tags: ')
        tags = obj.ntags
        for t in tags:
            res.add(trait.tag_link(tag=t, user=obj.user))
        if len(tags) > 0:
            res.add(T.br())
        res.add(T.a(f'{fdate(obj.when)}', href=obj.blink, cls='permalink'))
        res.add(' by')
        res.add(trait.user_link(user=obj.user))
        # TODO userstats
        return res

def reddit(s):
    return f'https://reddit.com{s}'

class ReachFormat(ForReach, FormatTrait):

    @classmethod
    def subreddit_link(cls, sub: str):
        subreddit_link = reddit('/r/' + sub)
        return T.a(sub, href=subreddit_link, cls='subreddit')

    @classmethod
    def format(trait, obj, *args, **kwargs) -> Htmlish:
        res = T.div(cls='reddit')
        ll = reddit(obj.link)

        ud = f'{obj.ups}⇅{obj.downs}'
        res.add(T.a(obj.title, href=ll))
        res.add(T.span(ud))
        res.add(T.br())

        if not isempty(obj.description):
            res.add(obj.description)
            res.add(T.br())
        res.add(T.div(trait.subreddit_link(obj.subreddit)))
        user_link = reddit('/u/' + obj.user)
        res.add(T.a(f'{obj.when.strftime("%Y-%m-%d %H:%M")}', href=ll, cls='permalink')); res.add(' by '); res.add(T.a(obj.user, href=user_link, cls='user'))
        return res

class TentacleTrait(ForTentacle, FormatTrait):
    # TODO mm. maybe permalink is a part of trait?
    @classmethod
    def format(trait, obj, *args, **kwargs) -> Htmlish:
        res = T.div(cls='github')
        res.add(T.a(obj.title, href=obj.link))
        res.add(T.span(f'{obj.stars}★'))
        res.add(T.br())
        if not isempty(obj.description):
            res.add(obj.description)
            res.add(T.br())
        res.add(T.a(f'{obj.when.strftime("%Y-%m-%d %H:%M")} by {obj.user}', href=obj.link, cls='permalink'))
        return res
        # TODO indicate how often is user showing up?

FormatTrait.reg(ReachFormat, SpinboardFormat, TentacleTrait)


# TODO hmm. instead percentile would be more accurate?...
def get_user_stats(jsons, rtype=None):
    cc = Collector()
    for jj in jsons:
        rev, dd, j = jj
        items = list(map(lambda x: from_json(rtype, x), j))
        cc.register(items)
    cnt = Counter([i.user for i in cc.items.values()])
    total = max(sum(cnt.values()), 1)
    return {
        u: v / total for u, v in cnt.items()
    }

# TODO search is a bit of flaky: initially I was getting
# so like exact opposites
# I guess removed links are basically not interesting, so we want to track whatever new was added

import requests
def send(subject: str, body: str, html=False):
    maybe_html: Dict[str, str] = {}
    if html:
        body = body.replace('\n', '\n<br>')
        maybe_html = {'html': body}
    return requests.post(
        "https://api.mailgun.net/v3/***REMOVED***.mailgun.org/messages",
        auth=(
            "api",
            "***REMOVED***" # TODO secrets..
        ),
        data={"from": "spinboard <mailgun@***REMOVED***.mailgun.org>",
              "to": ["karlicoss@gmail.com"],
              "subject": f"Spinboard stats for {subject}",
              # "text": body,
              **maybe_html,
        }
    )

STYLE = """

.item {
    margin-top:    10px;
    margin-bottom: 10px;
}

.item.ignored {
    color: gray;
    margin-top:    1px;
    margin-bottom: 1px;
}

.permalink {
    color: gray;
}

.day-changes-inner {
    margin-left: 15px;
}

.user {
    color: #035E7B;
}

.tag, .subreddit {
    color: darkgreen;
    /* color: #97130F; */
}

a:link {
  text-decoration: none;
}

a:visited {
  text-decoration: none;
}

a:hover {
  text-decoration: underline;
}

a:active {
  text-decoration: underline;
}
"""

JS = """
function hide(thing) {
// TODO ugh, doesn't look like $x works in FF
    const items = $x(`.//div[@class='item' and .//a[text()='${thing}']]`);
    console.log(`hiding ${items.length} items`);
    items.forEach(el => { el.hidden = true; });
}
"""

from kython import group_by_key
from kython.url import normalise
from functools import lru_cache
from collections import Counter

def vote(l):
    data = Counter(l)
    return data.most_common()[0][0]

# TODO kython??
# TODO tests next to function kinda like rust
def invkey(kk):
    from functools import cmp_to_key
    def icmp(a, b):
        ka = kk(a)
        kb = kk(b)
        if ka < kb:
            return 1
        elif ka > kb:
            return 1
        else:
            return 0
    return cmp_to_key(icmp)


class CumulativeBase(AbsTrait):
    def __init__(self, items: List) -> None:
        self.items = items

    @classproperty
    def FTrait(cls):
        return FormatTrait.for_(cls.Target)

    @cproperty
    def nlink(self) -> str:
        return normalise(self.items[0].link) # TODO not sure if useful..

    @property # type: ignore
    @lru_cache()
    def link(self) -> str:
        return vote(i.link for i in self.items)

    @property # type: ignore
    @lru_cache()
    def when(self) -> str:
        return min(x.when for x in self.items)

    @classproperty
    def cumkey(cls):
        raise NotImplementedError

    @classproperty
    def sortkey(cls):
        raise NotImplementedError

    @classmethod
    def sources_summary(cls, items):
        return f"No sources summary for {cls.Target} yet"

    @classmethod
    def sources_stats(cls, items, key):
        c = Counter()
        for i in items:
            kk = key(i)
            if not isinstance(kk, list):
                kk = [kk]
            for k in kk:
                c[k] += 1
        return list(sorted(c.items(), key=lambda p: (p[1], p[0])))

class SpinboardCumulative(ForSpinboard, CumulativeBase):
    @classproperty
    def cumkey(cls):
        return lambda x: normalise(x.link)

    @classproperty
    def sortkey(cls):
        return invkey(lambda c: c.when)

    # TODO shit, each of them is gonna require something individual??
    @property # type: ignore
    @lru_cache()
    def tags(self) -> List[str]:
        tt = {x for x in sum((i.ntags for i in self.items), [])}
        return list(sorted(tt))

    @property # type: ignore
    @lru_cache()
    def description(self) -> str:
        return vote(i.description for i in self.items)

    @property # type: ignore
    @lru_cache()
    def title(self) -> str:
        return vote(i.title for i in self.items)

    @property # type: ignore
    @lru_cache()
    def users(self) -> List[str]:
        uu = {x.user for x in self.items}
        return list(sorted(uu))

    def format(self):
        # TODO also display total count??
        res = T.div(cls='pinboard')
        res.add(T.a(self.title, href=self.link))
        res.add(T.br())
        if not isempty(self.description):
            res.add(self.description)
            res.add(T.br())
        res.add('tags: ')
        for t in self.tags:
            res.add(self.FTrait.tag_link(tag=t))
        res.add(T.br())
        pl = T.div(f'{fdate(self.when)} by', cls='permalink')
        fusers = [self.FTrait.user_link(user=u) for u in self.users]
        for f in fusers:
            pl.add(T.span(f))
        res.add(pl)
        return res

    @classmethod
    def sources_summary(cls, items):
        res = T.div()
        res.add(T.div(T.b('Tag summary:')))
        for src, cnt in cls.sources_stats(items, key=lambda i: i.ntags):
            x = T.div()
            x.add(cls.FTrait.tag_link(tag=src))
            x.add(f': {cnt}')
            res.add(x)
        # TODO dunno, it takes quite a bit of space... but cutting off those with 1 would be too annoying?
        res.add(T.div(T.b('User summary:')))
        for src, cnt in cls.sources_stats(items, key=lambda i: i.user):
            x = T.div()
            x.add(cls.FTrait.user_link(user=src))
            x.add(f': {cnt}')
            res.add(x)
        return res

CumulativeBase.reg(SpinboardCumulative)

class TentacleCumulative(ForTentacle, CumulativeBase):
    @classproperty
    def cumkey(cls):
        return lambda x: id(x)

    @classproperty
    def sortkey(cls):
        rev_when = invkey(lambda c: c.when)
        return lambda c: (c.stars, rev_when(c))

    @cproperty
    def stars(self) -> int:
        # TODO vote for method??
        return vote(i.stars for i in self.items)

    def format(self):
        assert len(self.items) == 1
        return self.FTrait.format(self.items[0])


CumulativeBase.reg(TentacleCumulative)

class ReachCumulative(ForReach, CumulativeBase):
    @cproperty
    def the(self):
        assert len(self.items) == 1
        return self.items[0]

    @cproperty
    def ups(self):
        return self.the.ups

    @cproperty
    def downs(self):
        return self.the.downs

    @classproperty
    def cumkey(cls):
        return lambda x: id(x)

    @classproperty
    def sortkey(cls):
        invwhen = invkey(lambda c: c.when)
        return lambda c: (c.ups + c.downs, invwhen(c))

    def format(self):
        return self.FTrait.format(self.the)

    @classmethod
    def sources_summary(cls, items):
        res = T.div()
        for sub, cnt in cls.sources_stats(items, key=lambda i: i.subreddit):
            x = T.div()
            x.add(cls.FTrait.subreddit_link(sub))
            x.add(f': {cnt}')
            res.add(x)
        return res

CumulativeBase.reg(ReachCumulative)


# https://github.com/Knio/dominate/issues/63
# eh, looks like it's the intended way..
def raw_script(s):
    raw(f'<script>{s}</script>')


def render_summary(repo: Path, digest: Changes[Any], rendered: Path) -> Path:
    rtype = get_result_type(repo) # TODO ??
    # ODO just get trait for type??

    Cumulative = CumulativeBase.for_(rtype)

    NOW = datetime.now()
    name = repo.name

    everything = flatten([ch for ch in digest.changes.values()])

    before = len(everything)

    grouped = group_by_key(everything, key=Cumulative.cumkey)
    print(f'before: {before}, after: {len(grouped)}')

    cumulatives = list(map(Cumulative, grouped.values()))
    cumulatives = list(sorted(cumulatives, key=Cumulative.sortkey))

    doc = dominate.document(title=f'axol results for {name}, rendered at {fdate(NOW)}')
    with doc.head:
        T.style(STYLE)
        raw_script(JS)
    with doc:
        T.h3("This is axol search summary")
        T.div("You can use 'hide' function in JS (chrome debugger) to hide certain tags/subreddits/users")
        T.h4("Sources summary")
        Cumulative.sources_summary(everything)
        for cc in cumulatives:
            T.div(cc.format(), cls='item')

    sf = rendered.joinpath(name + '.html')
    with sf.open('w') as fo:
        fo.write(str(doc))
    return sf

def render_latest(repo: Path, digest, rendered: Path):
    logger.info('processing %s', repo)

    NOW = datetime.now()

    name = repo.name
    doc = dominate.document(title=f'axol results for {name}, rendered at {fdate(NOW)}')

    with doc.head:
        T.style(STYLE)

    # TODO email that as well?
    with doc:
        for d, items in sorted(digest.changes.items(), reverse=True):
            logger.debug('dumping %d items for %s', len(items), d)
            with T.div(cls='day-changes'):
                T.div(T.b(fdate(d)))
                # TODO tab?
                with T.div(cls='day-changes-inner'):
                    for i in items:
                        ignored = ignore_result(i)
                        if ignored is not None:
                            # TODO maybe let format result handle that... not sure
                            T.div(ignored, cls='item ignored')
                            # TODO eh. need to handle in cumulatives...
                        else:
                            fi = format_result(i)
                            # TODO append raw?
                            T.div(fi, cls='item')

    rf = rendered.joinpath(name + '.html')
    with rf.open('w') as fo:
        fo.write(str(doc))
    return rf


def setup_parser(p):
    from config import BASE_DIR
    p.add_argument('repo', nargs='?')
    p.add_argument('--with-summary', action='store_true')
    p.add_argument('--with-tag-summary', action='store_true')
    p.add_argument('--last', type=int, default=None)
    p.add_argument('--output-dir', type=Path, default=BASE_DIR)


# TODO for starters, just send last few days digest..
def main():
    parser = argparse.ArgumentParser()
    setup_parser(parser)
    args = parser.parse_args()
    run(args)


def do_repo(repo, output_dir, last, summary: bool) -> Path:
    digest: Changes[Any] = get_digest(repo, last=last)
    RENDERED = output_dir / 'rendered'
    # TODO mm, maybe should return list of outputs..
    res = render_latest(repo, digest=digest, rendered=RENDERED)

    if summary:
        SUMMARY = output_dir/ 'summary'
        res = render_summary(repo, digest=digest, rendered=SUMMARY)
    return res


class Storage(NamedTuple):
    path: Path

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def source(self) -> str:
        return get_result_type(self.path)


def get_all_storages() -> Sequence[Storage]:
    return[Storage(path=x) for x in sorted(OUTPUTS.iterdir()) if x.is_dir()]


def run(args):
    res: List[Storage]
    if args.repo is not None:
        # TODO FIXME let it take several repos
        repos = [Storage(OUTPUTS.joinpath(args.repo))]
    else:
        repos = get_all_storages()

    logger.info('will be processing %s', repos)

    storages = repos
    odir = args.output_dir

    if args.with_tag_summary:
        tag_summary(repos, output_dir=args.output_dir)

    # TODO would be cool to do some sort of parallel logging? 
    # maybe some sort of rolling log using the whole terminal screen?
    errors: List[str] = []

    # from kython.koncurrent import DummyExecutor
    # pool = DummyExecutor()
    pool = ProcessPoolExecutor()
    with pool:
        # TODO this is just pool map??
        futures = []
        for repo in repos:
            futures.append(pool.submit(do_repo, repo.path, output_dir=args.output_dir, last=args.last, summary=args.with_summary))
        for r, f in zip(repos, futures):
            try:
                f.result()
            except Exception as e:
                logger.error('while processing %s', r)
                logger.exception(e)
                err = f'while processing {r}: {e}'
                errors.append(err)

    # TODO put errors on index page?
    write_index(storages, odir)


    if len(errors) > 0:
        for e in errors:
            logger.error(e)
        sys.exit(1)


if __name__ == '__main__':
    main()
# TODO how to make it generic to incorporate github??


# basically a thing that knows how to fetch items with timestsamps
# and notify of new ones..

# TODO need to plot some nice dashboard..

def astext(html: Path) -> str:
    from subprocess import check_output
    return check_output(['html2text', str(html)]).decode('utf8')


def test_all(tmp_path):
    tdir = Path(tmp_path)
    repo = OUTPUTS / 'bret_victor'
    digest = get_digest(repo)
    render_latest(repo, digest=digest, rendered=tdir)
    out = tdir / 'bret_victor.html'

    ht = out.read_text()

    assert 'http://worrydream.com/MagicInk/' in ht
    assert 'http://enjalot.com/' in ht


    text = astext(out).splitlines()
    def tcontains(x):
        for line in text:
            if x in line:
                return True
        return False

    assert tcontains('Tue 18 Jun 2019 13:10')
    assert tcontains('Fri_14_Jun_2019_14:33 by pmf')
    assert tcontains('tags: bret_victor javascript mar12 visualization')


def write_index(storages, output_dir: Path):
    now = datetime.now()
    doc = dominate.document(title=f'axol index for {[s.name for s in storages]}, rendered at {fdate(now)}')
    with doc.head:
        T.style(STYLE)

    with doc.body:
        with T.table():
            for storage in storages:
                with T.tr():
                    T.td(storage.name)
                    T.td(T.a('summary', href=f'summary/{storage.name}.html'))
                    T.td(T.a('history', href=f'rendered/{storage.name}.html'))
        with T.div():
            T.b(T.a('pinboard tag summary', href=f'pinboard_tags.html'))

    # TODO 'last updated'?
    (output_dir / 'index.html').write_text(str(doc))


def tag_summary(storages, output_dir: Path):
    from spinboard import Result # type: ignore
    logger.warning('filtering pinboard only (FIXME)')
    storages = [s for s in storages if s.source == Result]

    ustats = {}
    def reg(user, query, stats):
        if user not in ustats:
            ustats[user] = {}
        ustats[user][query] = stats

    with ProcessPoolExecutor() as pp:
        digests = pp.map(get_digest, [s.path for s in storages])

    for s, digest in zip(storages, digests):
        everything = flatten([ch for ch in digest.changes.values()])
        for user, items in group_by_key(everything, key=lambda x: x.user).items():
            reg(user, s.name, f'{len(items)}')

    now = datetime.now()
    doc = dominate.document(title=f'axol tags summary for {[s.name for s in storages]}, rendered at {fdate(now)}')
    with doc.head:
        T.style(STYLE)
        raw_script(JS) # TODO necessary?

    ft = FormatTrait.for_(Result)
    with doc.body:
        with T.table():
            for user, stats in sorted(ustats.items(), key=lambda x: (-len(x[1]), x)):
                with T.tr():
                    T.td(ft.user_link(user))
                    for q, st in stats.items():
                        with T.td():
                            # TODO I guess unclear which tag to choose though.
                            T.a(q, href=f'summary/{q}.html') # TODO link to source in index? or on pinboard maybe
                            # TODO also project onto user's tags straight away
                            T.sup(st)

    out = (output_dir / 'pinboard_tags.html')
    out.write_text(str(doc))
    logger.info('Dumped tag summary to %s', out)

