<?php
header('Content-Type: text/html; charset=UTF-8');
header('Cache-Control: no-store');
$file = __DIR__ . '/.analytics/summary.json';
$data = is_file($file) ? json_decode((string)file_get_contents($file), true) : null;
if (!is_array($data)) {
    $data = ['totals'=>['page_view'=>0,'start'=>0,'complete'=>0,'share'=>0,'result_view'=>0],'results'=>array_fill(0,8,0),'daily'=>[],'updated_at'=>null];
}
$t = $data['totals'];
$rate = static function($a,$b){ return $b > 0 ? round($a / $b * 100, 1) : 0; };
$types = ['計画ガチ勢','全力エンジョイ勢','コツコツ安定型','最終日覚醒型','自由研究研究者','マイペース職人','思い出コレクター','宿題消失マジシャン'];
$daily = array_reverse(array_slice($data['daily'], -14, 14, true), true);
?>
<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>noinoi LAB 計測</title><style>
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f8fafc;color:#0f172a}.wrap{max-width:900px;margin:auto;padding:24px 16px 70px}h1{font-size:32px;margin:0 0 6px}.sub{color:#64748b}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:22px 0}.card{background:#fff;border-radius:18px;padding:18px;box-shadow:0 8px 28px rgba(15,23,42,.07)}.num{font-size:32px;font-weight:900}.label{font-size:13px;color:#64748b;margin-top:4px}.rate{font-size:14px;color:#0f766e;font-weight:800;margin-top:6px}table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:right;padding:10px 8px;border-bottom:1px solid #e2e8f0}th:first-child,td:first-child{text-align:left}.bar{height:10px;background:#e2e8f0;border-radius:999px;overflow:hidden;margin-top:6px}.fill{height:100%;background:#f97316}.foot{font-size:12px;color:#94a3b8;margin-top:18px;line-height:1.6}a{color:#2563eb}
</style></head><body><main class="wrap"><h1>アクセス計測</h1><p class="sub">夏休みタイプ診断 / test.noinoi.xyz</p>
<div class="grid">
<div class="card"><div class="num"><?= (int)$t['page_view'] ?></div><div class="label">ページ表示</div></div>
<div class="card"><div class="num"><?= (int)$t['start'] ?></div><div class="label">診断開始</div><div class="rate">開始率 <?= $rate($t['start'],$t['page_view']) ?>%</div></div>
<div class="card"><div class="num"><?= (int)$t['complete'] ?></div><div class="label">診断完了</div><div class="rate">完了率 <?= $rate($t['complete'],$t['start']) ?>%</div></div>
<div class="card"><div class="num"><?= (int)$t['share'] ?></div><div class="label">シェア操作</div><div class="rate">シェア率 <?= $rate($t['share'],$t['complete']) ?>%</div></div>
<div class="card"><div class="num"><?= (int)$t['result_view'] ?></div><div class="label">結果URLから流入</div></div>
</div>
<section class="card"><h2>診断結果の内訳</h2><?php $max=max(1,...array_map('intval',$data['results'])); foreach($types as $i=>$name): $v=(int)($data['results'][$i]??0); ?><div style="margin:14px 0"><strong><?= htmlspecialchars($name,ENT_QUOTES,'UTF-8') ?></strong> <span style="float:right"><?= $v ?></span><div class="bar"><div class="fill" style="width:<?= round($v/$max*100,1) ?>%"></div></div></div><?php endforeach; ?></section>
<section class="card" style="margin-top:14px"><h2>直近14日</h2><div style="overflow:auto"><table><thead><tr><th>日付</th><th>表示</th><th>開始</th><th>完了</th><th>共有</th><th>結果流入</th></tr></thead><tbody><?php foreach($daily as $d=>$v): ?><tr><td><?= htmlspecialchars($d,ENT_QUOTES,'UTF-8') ?></td><td><?= (int)$v['page_view'] ?></td><td><?= (int)$v['start'] ?></td><td><?= (int)$v['complete'] ?></td><td><?= (int)$v['share'] ?></td><td><?= (int)$v['result_view'] ?></td></tr><?php endforeach; ?></tbody></table></div></section>
<p class="foot">個人情報・IPアドレス・Cookieは保存せず、イベント件数だけを集計しています。ページの再読み込みはページ表示として再カウントされます。<br><a href="./">診断へ戻る</a></p></main></body></html>
