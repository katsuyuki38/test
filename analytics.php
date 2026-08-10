<?php
header('Content-Type: application/json; charset=UTF-8');
header('Cache-Control: no-store');

$allowed = ['page_view','start','complete','share','result_view'];
$event = $_POST['event'] ?? $_GET['event'] ?? '';
$result = $_POST['result'] ?? $_GET['result'] ?? '';

if (!in_array($event, $allowed, true)) {
    http_response_code(400);
    echo json_encode(['ok' => false, 'error' => 'invalid_event'], JSON_UNESCAPED_UNICODE);
    exit;
}

$dir = __DIR__ . '/.analytics';
if (!is_dir($dir)) {
    @mkdir($dir, 0755, true);
}

$file = $dir . '/summary.json';
$fp = @fopen($file, 'c+');
if (!$fp) {
    http_response_code(500);
    echo json_encode(['ok' => false, 'error' => 'storage_unavailable'], JSON_UNESCAPED_UNICODE);
    exit;
}

flock($fp, LOCK_EX);
$raw = stream_get_contents($fp);
$data = $raw ? json_decode($raw, true) : null;
if (!is_array($data)) {
    $data = [
        'totals' => ['page_view'=>0,'start'=>0,'complete'=>0,'share'=>0,'result_view'=>0],
        'results' => array_fill(0, 8, 0),
        'daily' => [],
        'updated_at' => null
    ];
}

$today = date('Y-m-d');
if (!isset($data['daily'][$today])) {
    $data['daily'][$today] = ['page_view'=>0,'start'=>0,'complete'=>0,'share'=>0,'result_view'=>0];
}
$data['totals'][$event] = ($data['totals'][$event] ?? 0) + 1;
$data['daily'][$today][$event] = ($data['daily'][$today][$event] ?? 0) + 1;

if ($event === 'complete' && ctype_digit((string)$result)) {
    $n = (int)$result;
    if ($n >= 0 && $n <= 7) {
        $data['results'][$n] = ($data['results'][$n] ?? 0) + 1;
    }
}

$data['updated_at'] = date('c');
rewind($fp);
ftruncate($fp, 0);
fwrite($fp, json_encode($data, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT));
fflush($fp);
flock($fp, LOCK_UN);
fclose($fp);

echo json_encode(['ok' => true], JSON_UNESCAPED_UNICODE);
