//! Parquet writers with the same schemas as parse.py writes (pyarrow), ZSTD level 6.
use arrow_array::builder::{
    BooleanBuilder, FixedSizeBinaryBuilder, Int32Builder, Int64Builder, ListBuilder, StringBuilder,
};
use arrow_array::{ArrayRef, RecordBatch};
use arrow_schema::{DataType, Field, Schema};
use parquet::arrow::ArrowWriter;
use parquet::basic::{Compression, ZstdLevel};
use parquet::file::properties::WriterProperties;
use std::fs::File;
use std::sync::Arc;

use crate::model::Id;

fn b16() -> DataType {
    DataType::FixedSizeBinary(16)
}
fn list(t: DataType) -> DataType {
    DataType::List(Arc::new(Field::new("item", t, true)))
}
fn f(name: &str, t: DataType) -> Field {
    Field::new(name, t, true)
}

pub fn schema(table: &str) -> Arc<Schema> {
    let s = DataType::Utf8;
    Arc::new(Schema::new(match table {
        "provider_group" => vec![
            f("pg_id", b16()), f("tin_type", s.clone()), f("tin_value", s.clone()), f("tin_raw", s.clone()),
            f("npis", list(DataType::Int64)), f("npi_count", DataType::Int32), f("tin_wide", DataType::Boolean),
            f("business_names", list(s.clone())),
        ],
        "provider_set" => vec![f("ps_id", b16()), f("pli_ids", list(b16()))],
        "provider_list" => vec![f("pli_id", b16()), f("pg_ids", list(b16()))],
        "provider_reference" => vec![
            f("provider_group_id", s.clone()), f("pg_ids", list(b16())), f("network_name", list(s.clone())),
            f("location", s.clone()),
        ],
        "price_term" => vec![
            f("pt_id", b16()), f("negotiated_type", s.clone()), f("rate_e4", DataType::Int64), f("rate_raw", s.clone()),
            f("billing_class", s.clone()), f("setting", s.clone()), f("service_code", list(s.clone())),
            f("service_code_raw", s.clone()), f("billing_code_modifier", list(s.clone())),
            f("expiration_date", s.clone()), f("additional_information", s.clone()),
            f("applies_to_revenue_codes", list(s.clone())), f("extra", s.clone()), f("flags", list(s.clone())),
        ],
        "price_list" => vec![f("pl_id", b16()), f("pt_ids", list(b16()))],
        "code" => vec![
            f("code_id", b16()), f("negotiation_arrangement", s.clone()), f("billing_code_type", s.clone()),
            f("billing_code_type_version", s.clone()), f("billing_code", s.clone()), f("billing_code_raw", s.clone()),
            f("name", s.clone()), f("description", s.clone()), f("severity_of_illness", s.clone()), f("bundle", s.clone()),
        ],
        "rate_fact" => vec![
            f("fact_id", b16()), f("code_id", b16()), f("ps_id", b16()), f("pl_id", b16()), f("block_id", b16()),
            f("billing_code_type", s.clone()), f("billing_code", s.clone()),
        ],
        "file_block" => vec![f("block_id", b16()), f("code_id", b16()), f("part", DataType::Int32), f("n_rates", DataType::Int32)],
        other => panic!("unknown table {other}"),
    }))
}

pub struct Pq {
    w: ArrowWriter<File>,
    pub rows: u64,
    pub path: String,
}

impl Pq {
    pub fn create(path: &str, table: &str) -> Pq {
        let props = WriterProperties::builder()
            .set_compression(Compression::ZSTD(ZstdLevel::try_new(3).unwrap()))
            .set_max_row_group_size(1_000_000)
            .build();
        let file = File::create(path).expect("create parquet");
        Pq { w: ArrowWriter::try_new(file, schema(table), Some(props)).expect("writer"), rows: 0, path: path.into() }
    }
    pub fn write(&mut self, cols: Vec<ArrayRef>, table: &str) {
        let b = RecordBatch::try_new(schema(table), cols).expect("batch");
        self.rows += b.num_rows() as u64;
        self.w.write(&b).expect("write");
        // a row group of a list table can hold gigabytes before it reaches the row limit
        if self.w.in_progress_size() > 256 << 20 {
            self.w.flush().expect("flush row group");
        }
    }
    pub fn close(self) -> (u64, u64) {
        let rows = self.rows;
        let path = self.path.clone();
        self.w.close().expect("close");
        (rows, std::fs::metadata(path).map(|m| m.len()).unwrap_or(0))
    }
}

// ------------------------------------------------------------------ row types

pub struct PgRow {
    pub pg_id: Id,
    pub tin_type: Option<String>,
    pub tin_value: Option<String>,
    pub tin_raw: Option<String>,
    pub npis: Vec<i64>,
    pub tin_wide: bool,
    pub business_names: Vec<String>,
}
pub struct PtRow {
    pub pt_id: Id,
    pub negotiated_type: Option<String>,
    pub rate_e4: Option<i64>,
    pub rate_raw: Option<String>,
    pub billing_class: Option<String>,
    pub setting: Option<String>,
    pub service_code: Vec<String>,
    pub service_code_raw: Option<String>,
    pub billing_code_modifier: Vec<String>,
    pub expiration_date: Option<String>,
    pub additional_information: Option<String>,
    pub applies_to_revenue_codes: Vec<String>,
    pub extra: Option<String>,
    pub flags: Vec<String>,
}
pub struct CodeRow {
    pub code_id: Id,
    pub negotiation_arrangement: Option<String>,
    pub billing_code_type: Option<String>,
    pub billing_code_type_version: Option<String>,
    pub billing_code: Option<String>,
    pub billing_code_raw: Option<String>,
    pub name: Option<String>,
    pub description: Option<String>,
    pub severity_of_illness: Option<String>,
    pub bundle: Option<String>,
}
pub struct RefRow {
    pub provider_group_id: Option<String>,
    pub pg_ids: Vec<Id>,
    pub network_name: Vec<String>,
    pub location: Option<String>,
}
pub struct FactRow {
    pub fact_id: Id,
    pub code_id: Id,
    pub ps_id: Id,
    pub pl_id: Id,
    pub block_id: Id,
    pub billing_code_type: Option<Arc<str>>,
    pub billing_code: Option<Arc<str>>,
}

// ------------------------------------------------------------------ column builders

fn ids(v: impl Iterator<Item = Id>) -> ArrayRef {
    let mut b = FixedSizeBinaryBuilder::new(16);
    for x in v {
        b.append_value(x).unwrap();
    }
    Arc::new(b.finish())
}
fn strs<'a>(v: impl Iterator<Item = Option<&'a str>>) -> ArrayRef {
    let mut b = StringBuilder::new();
    for x in v {
        b.append_option(x);
    }
    Arc::new(b.finish())
}
fn str_lists<'a>(v: impl Iterator<Item = &'a Vec<String>>) -> ArrayRef {
    let mut b = ListBuilder::new(StringBuilder::new());
    for l in v {
        for s in l {
            b.values().append_value(s);
        }
        b.append(true);
    }
    Arc::new(b.finish())
}
fn id_lists<'a>(v: impl Iterator<Item = &'a Vec<Id>>) -> ArrayRef {
    let mut b = ListBuilder::new(FixedSizeBinaryBuilder::new(16));
    for l in v {
        for x in l {
            b.values().append_value(x).unwrap();
        }
        b.append(true);
    }
    Arc::new(b.finish())
}

pub fn pg_cols(rows: &[PgRow]) -> Vec<ArrayRef> {
    let mut npis = ListBuilder::new(Int64Builder::new());
    for r in rows {
        for n in &r.npis {
            npis.values().append_value(*n);
        }
        npis.append(true);
    }
    let mut cnt = Int32Builder::new();
    let mut tw = BooleanBuilder::new();
    for r in rows {
        cnt.append_value(r.npis.len() as i32);
        tw.append_value(r.tin_wide);
    }
    vec![
        ids(rows.iter().map(|r| r.pg_id)),
        strs(rows.iter().map(|r| r.tin_type.as_deref())),
        strs(rows.iter().map(|r| r.tin_value.as_deref())),
        strs(rows.iter().map(|r| r.tin_raw.as_deref())),
        Arc::new(npis.finish()),
        Arc::new(cnt.finish()),
        Arc::new(tw.finish()),
        str_lists(rows.iter().map(|r| &r.business_names)),
    ]
}

pub fn ps_cols(rows: &[(Id, Vec<Id>)]) -> Vec<ArrayRef> {
    vec![ids(rows.iter().map(|r| r.0)), id_lists(rows.iter().map(|r| &r.1))]
}

pub fn ref_cols(rows: &[RefRow]) -> Vec<ArrayRef> {
    vec![
        strs(rows.iter().map(|r| r.provider_group_id.as_deref())),
        id_lists(rows.iter().map(|r| &r.pg_ids)),
        str_lists(rows.iter().map(|r| &r.network_name)),
        strs(rows.iter().map(|r| r.location.as_deref())),
    ]
}

pub fn pt_cols(rows: &[PtRow]) -> Vec<ArrayRef> {
    let mut e4 = Int64Builder::new();
    for r in rows {
        e4.append_option(r.rate_e4);
    }
    vec![
        ids(rows.iter().map(|r| r.pt_id)),
        strs(rows.iter().map(|r| r.negotiated_type.as_deref())),
        Arc::new(e4.finish()),
        strs(rows.iter().map(|r| r.rate_raw.as_deref())),
        strs(rows.iter().map(|r| r.billing_class.as_deref())),
        strs(rows.iter().map(|r| r.setting.as_deref())),
        str_lists(rows.iter().map(|r| &r.service_code)),
        strs(rows.iter().map(|r| r.service_code_raw.as_deref())),
        str_lists(rows.iter().map(|r| &r.billing_code_modifier)),
        strs(rows.iter().map(|r| r.expiration_date.as_deref())),
        strs(rows.iter().map(|r| r.additional_information.as_deref())),
        str_lists(rows.iter().map(|r| &r.applies_to_revenue_codes)),
        strs(rows.iter().map(|r| r.extra.as_deref())),
        str_lists(rows.iter().map(|r| &r.flags)),
    ]
}

pub fn pl_cols(rows: &[(Id, Vec<Id>)]) -> Vec<ArrayRef> {
    vec![ids(rows.iter().map(|r| r.0)), id_lists(rows.iter().map(|r| &r.1))]
}

pub fn code_cols(rows: &[CodeRow]) -> Vec<ArrayRef> {
    vec![
        ids(rows.iter().map(|r| r.code_id)),
        strs(rows.iter().map(|r| r.negotiation_arrangement.as_deref())),
        strs(rows.iter().map(|r| r.billing_code_type.as_deref())),
        strs(rows.iter().map(|r| r.billing_code_type_version.as_deref())),
        strs(rows.iter().map(|r| r.billing_code.as_deref())),
        strs(rows.iter().map(|r| r.billing_code_raw.as_deref())),
        strs(rows.iter().map(|r| r.name.as_deref())),
        strs(rows.iter().map(|r| r.description.as_deref())),
        strs(rows.iter().map(|r| r.severity_of_illness.as_deref())),
        strs(rows.iter().map(|r| r.bundle.as_deref())),
    ]
}

pub fn fact_cols(rows: &[FactRow]) -> Vec<ArrayRef> {
    vec![
        ids(rows.iter().map(|r| r.fact_id)),
        ids(rows.iter().map(|r| r.code_id)),
        ids(rows.iter().map(|r| r.ps_id)),
        ids(rows.iter().map(|r| r.pl_id)),
        ids(rows.iter().map(|r| r.block_id)),
        strs(rows.iter().map(|r| r.billing_code_type.as_deref())),
        strs(rows.iter().map(|r| r.billing_code.as_deref())),
    ]
}

pub struct FbRow {
    pub block_id: Id,
    pub code_id: Id,
    pub part: i32,
    pub n_rates: i32,
}

pub fn fb_cols(rows: &[FbRow]) -> Vec<ArrayRef> {
    let mut p = Int32Builder::new();
    let mut n = Int32Builder::new();
    for r in rows {
        p.append_value(r.part);
        n.append_value(r.n_rates);
    }
    vec![ids(rows.iter().map(|r| r.block_id)), ids(rows.iter().map(|r| r.code_id)), Arc::new(p.finish()), Arc::new(n.finish())]
}
