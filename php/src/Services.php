<?php
declare(strict_types=1);

namespace Jq;

/** Корень сборки: создаёт все части приложения один раз и раздаёт контроллерам. */
final class Services
{
    public readonly Db $db;
    public readonly Schema $schema;
    public readonly Validator $validator;
    public readonly Summary $summary;
    public readonly Leads $leads;
    public readonly Files $files;
    public readonly Limiter $limiter;
    public readonly Telegram $tg;
    public readonly Subscribers $subs;
    public readonly Notifier $notifier;
    public readonly Maintenance $maintenance;
    public readonly Auth $auth;

    public function __construct(public readonly Config $cfg)
    {
        $cfg->ensureDirs();
        $this->db = Db::open($cfg->dataDir . '/leads.db');
        $this->schema = Schema::load($cfg->publicDir . '/schema.json');
        $this->validator = new Validator($this->schema);
        $this->summary = new Summary($this->schema, $cfg);
        $this->leads = new Leads($this->db, $this->summary);
        $this->files = new Files($cfg, $this->db);
        $this->limiter = new Limiter($this->db, $cfg);
        $this->tg = new Telegram($cfg);
        $this->subs = new Subscribers($cfg, $this->db, $this->tg, $this->limiter);
        $this->notifier = new Notifier($cfg, $this->db, $this->tg, $this->files, $this->summary, $this->subs);
        $this->maintenance = new Maintenance($cfg, $this->db, $this->notifier, $this->files, $this->limiter);
        $this->auth = new Auth($cfg, $this->limiter);
    }
}
