import { test } from 'node:test';
import assert from 'node:assert/strict';
import { relationDetails } from './relation-details.mjs';

test('detalhes achatam valores simples e deixam mídia e textos longos de fora', () => {
  const d = relationDetails({
    id: '7000', status: 1, create_time_second: '1700000000',
    creator_info: {
      user_name: 'teste', nick_name: 'Teste', follower_cnt: 1255, avatar: { url_list: ['https://x/a.jpg'] },
      categories: ['Beleza', 'Digital'], level: { current: 0, estimated: 1, gmv: '0.00' },
      bio: 'x'.repeat(400), link: 'https://www.tiktok.com/@teste', verified: true,
    },
    data_relation: { effective_end_date_second: '1800000000', can_extend: false },
    big: Array.from({ length: 50 }, (_, i) => ({ i })),
  });
  assert.equal(d.id, '7000');
  assert.equal(d['creator_info.follower_cnt'], 1255);
  assert.deepEqual(d['creator_info.categories'], ['Beleza', 'Digital']);
  assert.equal(d['creator_info.level.estimated'], 1);
  assert.equal(d['creator_info.verified'], true);
  assert.equal(d['data_relation.can_extend'], false);
  assert.ok(!Object.keys(d).some((k) => k.includes('avatar')));
  assert.equal(d['creator_info.bio'], undefined);
  assert.equal(d['creator_info.link'], undefined);
  assert.ok(Object.keys(d).filter((k) => k.startsWith('big.')).length <= 10);
});

test('limite de chaves e entradas vazias', () => {
  const many = Object.fromEntries(Array.from({ length: 500 }, (_, i) => [`k${i}`, i]));
  assert.ok(Object.keys(relationDetails(many)).length <= 200);
  assert.deepEqual(relationDetails(null), {});
  assert.deepEqual(relationDetails(undefined), {});
});
