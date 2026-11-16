"""Source-bound article evidence; no model calls or event judgements."""

import archive
import event_facts

RULE_VERSION = 'article-evidence-v1'


def attach(articles):
    records = archive.provenance(list(dict.fromkeys(a['url'] for a in articles)))
    for article in articles:
        record = records.get(article['url'], {})
        matches = bool(record and record['title'] == article['title'])
        article['evidence'] = {
            'rule_version': RULE_VERSION,
            'assessment_status': 'not_analyzed',
            'classification_status': 'keyword_only' if article.get('themes') else 'unclassified',
            'source_status': ('body_available' if record.get('body_version') else 'title_only') if matches else 'source_missing',
            'source_url': article['url'],
            'source_excerpt': article['title'] if matches else None,
            'body_title_binding': 'unverified' if matches and record.get('body_version') else None,
            'published_at': article.get('published_at') if article.get('timestamp_basis') != 'portal_display' else None,
            'portal_display_at': article.get('published_at') if article.get('timestamp_basis') == 'portal_display' else None,
            **{k:record.get(k) if matches else None for k in ('article_version','first_seen_at','article_version_seen_at',
                                                          'body_version','body_observed_at','body_excerpt')},
        }
    return event_facts.attach(articles)
