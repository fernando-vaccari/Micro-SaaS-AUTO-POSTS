export const MAX_UPLOAD=4*1024*1024;
export function publicConfig(env=process.env,code='BACKEND_NOT_CONFIGURED'){
  return {edition:env.APP_EDITION==='demo'?'demo':'saas',production:true,backend_connected:false,
    service_ready:false,deployment_status:code,publishing_enabled:false,billing_enabled:false,
    max_upload_bytes:MAX_UPLOAD,media_ttl_hours:10,operator:env.LEGAL_OPERATOR_NAME||'',contact:env.LEGAL_CONTACT_EMAIL||''};
}
export function publicPlans(env=process.env){
  const number=(key,fallback)=>{const value=Number(env[key]||fallback);if(!Number.isSafeInteger(value)||value<1||value>1_000_000)throw new Error('PUBLIC_CATALOG_CONFIGURATION_INVALID');return value;};
  return [{id:'studio',name:'Studio',price_cents:number('PLAN_STUDIO_PRICE_CENTS',14999),currency:'BRL',
    videos:number('PLAN_STUDIO_VIDEOS',20),images:number('PLAN_STUDIO_IMAGES',40),trial_days:0}];
}
export function bootstrap(env=process.env){return {session:{user:null,csrf_token:null,service_ready:false,integrations:{}},plans:publicPlans(env),config:publicConfig(env,'API_UNAVAILABLE')};}
