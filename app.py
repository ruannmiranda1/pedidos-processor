from fastapi import FastAPI, Request
from bs4 import BeautifulSoup
import json
import re

app = FastAPI()

@app.get("/")
async def root():
    return {"status": "online", "version": "4.3"}

def converter_valor_brasileiro(valor_str: str) -> str:
    """
    Converte valores do formato brasileiro para formato numérico.
    Exemplos:
    - "18.629,20" -> "18629.20"
    - "9.455,00" -> "9455.00"
    - "373,50" -> "373.50"
    - "1.620,00" -> "1620.00"
    - "2.545,00" -> "2545.00"
    """
    try:
        # Remove espaços
        valor_limpo = valor_str.strip()
        
        # Remove qualquer caractere que não seja número, ponto ou vírgula
        valor_limpo = re.sub(r'[^\d,.]', '', valor_limpo)
        
        if not valor_limpo:
            return "0"
        
        # Se tem vírgula, é formato brasileiro
        if ',' in valor_limpo:
            # Remove pontos (separador de milhar)
            valor_sem_pontos = valor_limpo.replace('.', '')
            # Troca vírgula por ponto (decimal)
            valor_final = valor_sem_pontos.replace(',', '.')
        else:
            # Não tem vírgula, só ponto
            partes = valor_limpo.split('.')
            
            if len(partes) == 2 and len(partes[1]) == 2:
                # Provavelmente decimal: "373.50"
                valor_final = valor_limpo
            else:
                # Provavelmente milhar: "1.234" -> "1234"
                valor_final = valor_limpo.replace('.', '')
        
        # Valida se é um número válido
        float(valor_final)
        
        return valor_final
        
    except Exception as e:
        print(f"❌ Erro ao converter valor '{valor_str}': {e}")
        return "0"

@app.post("/processar-faturamento")
async def processar_faturamento(request: Request):
    """
    Lê o HTML do email de faturamento e devolve lista de objetos:
    [
      {
        "Cod. Cli./For.": "...",
        "Cliente/Fornecedor": "...",
        "Data": "01/10/2025",
        "Total Item": "502.50",
        "Vendedor": "...",
        "Ref. Produto": "...",
        "Des. Grupo Completa": "...",
        "Marca": "...",
        "Cidade": "...",
        "Estado": "..."
      }
    ]
    """
    try:
        body = await request.body()
        body_str = body.decode("utf-8").strip()

        try:
            payload = json.loads(body_str)
            html = payload.get("html_email", "")
        except:
            html = body_str

        if not html:
            return []

        html = re.sub(r"[\r\n\t]+", " ", html)
        soup = BeautifulSoup(html, "html.parser")
        faturamento = []

        for tr in soup.find_all("tr"):
            classes = tr.get("class", []) or []
            if not any("destac" in str(c) for c in classes):
                continue

            cells = tr.find_all("td")
            if len(cells) < 16:
                print(f"⚠️ Linha ignorada (só {len(cells)} colunas)")
                continue

            try:
                cod_cli_for = cells[0].get_text(strip=True)
                cliente = cells[1].get_text(strip=True)
                data = cells[2].get_text(strip=True)
                ref_produto = cells[5].get_text(strip=True)
                grupo = cells[7].get_text(strip=True)
                total_str = cells[9].get_text(strip=True)
                vendedor = cells[11].get_text(strip=True)
                marca = cells[12].get_text(strip=True)
                cidade = cells[13].get_text(strip=True)
                estado = cells[14].get_text(strip=True)

                total = converter_valor_brasileiro(total_str)

                if not cliente or not total:
                    continue

                item = {
                    "Cod. Cli./For.": cod_cli_for,
                    "Cliente/Fornecedor": cliente,
                    "Data": data,
                    "Total Item": total,
                    "Vendedor": vendedor,
                    "Ref. Produto": ref_produto,
                    "Des. Grupo Completa": grupo,
                    "Marca": marca,
                    "Cidade": cidade,
                    "Estado": estado
                }
                faturamento.append(item)

                print(f"💰 {cliente[:35]}... | R$ {total} | {vendedor[:30]}")

            except Exception as e:
                print(f"⚠️ Erro na linha: {e}")
                for i in range(min(len(cells), 16)):
                    print(f"   cells[{i}] = {cells[i].get_text(strip=True)}")
                continue

        print(f"📦 Total processado: {len(faturamento)} registros de faturamento")
        return faturamento

    except Exception as e:
        print(f"❌ Erro geral: {e}")
        import traceback
        traceback.print_exc()
        return []

@app.post("/processar-pedidos")
async def processar_pedidos(request: Request):
    """
    Processa HTML de email e retorna array de pedidos.
    
    ⚠️ ATENÇÃO: O HTML recebido tem tags <tr> malformadas (não fechadas).
    Usamos html5lib parser que é mais tolerante a HTML malformado.
    
    ESTRUTURA ESPERADA DA TABELA (12 colunas):
    cells[0]  = Data
    cells[1]  = DtEntrPro (Entrega Prod.)
    cells[2]  = Nr. Ped
    cells[3]  = Cod. Cli
    cells[4]  = Cliente
    cells[5]  = Cod. Vend
    cells[6]  = Vendedor
    cells[7]  = Prazo
    cells[8]  = CFOP
    cells[9]  = Sit. Fat
    cells[10] = Total
    cells[11] = Empresa
    """
    try:
        body = await request.body()
        body_str = body.decode('utf-8').strip()
        
        try:
            payload = json.loads(body_str)
            html = payload.get("html_email", "")
        except:
            html = body_str
        
        if not html:
            print("❌ HTML vazio!")
            return []
        
        print(f"📥 HTML recebido: {len(html)} caracteres")
        
        # ✅ USA html5lib PARA PARSEAR HTML MALFORMADO
        # O html5lib corrige automaticamente tags não fechadas
        try:
            soup = BeautifulSoup(html, 'html5lib')
        except:
            # Fallback para html.parser se html5lib não estiver disponível
            print("⚠️ html5lib não disponível, usando html.parser")
            soup = BeautifulSoup(html, 'html.parser')
        
        pedidos = []
        linhas_processadas = 0
        linhas_ignoradas = 0
        
        print("🔍 Procurando linhas com classe 'destaca' ou 'destacb'...")
        
        # Procura todas as linhas com classe "destaca" ou "destacb"
        for tr in soup.find_all('tr'):
            classes = tr.get('class', []) if tr.get('class') else []
            
            # Debug: mostra todas as classes encontradas
            if classes:
                print(f"   Encontrada linha com classe: {classes}")
            
            # Verifica se tem classe de pedido
            if not any('destac' in str(c) for c in classes):
                continue
            
            cells = tr.find_all('td')
            linhas_processadas += 1
            
            print(f"\n📋 Processando linha {linhas_processadas} com {len(cells)} células")
            
            # ✅ ACEITA 12 COLUNAS (ESTRUTURA COMPLETA)
            if len(cells) != 12:
                print(f"⚠️ Linha {linhas_processadas} ignorada: tem {len(cells)} células (esperado 12)")
                linhas_ignoradas += 1
                
                # 🐛 DEBUG: Mostra o conteúdo das células
                for i, cell in enumerate(cells[:15]):  # Mostra até 15 células
                    texto = cell.get_text(strip=True)[:60]
                    print(f"   cells[{i}] = {texto}")
                
                continue
            
            try:
                # ✅ EXTRAÇÃO COM ÍNDICES CORRETOS (12 colunas)
                data_pedido = cells[0].get_text(strip=True)      # Data
                entrega_prod = cells[1].get_text(strip=True)     # DtEntrPro
                nr_pedido = cells[2].get_text(strip=True)        # Nr. Ped
                cod_cli = cells[3].get_text(strip=True)          # Cod. Cli
                cliente = cells[4].get_text(strip=True)          # Cliente
                cod_vend = cells[5].get_text(strip=True)         # Cod. Vend
                vendedor = cells[6].get_text(strip=True)         # Vendedor
                prazo = cells[7].get_text(strip=True)            # Prazo
                cfop = cells[8].get_text(strip=True)             # CFOP
                sit_fat = cells[9].get_text(strip=True)          # Sit. Fat
                total_str = cells[10].get_text(strip=True)       # Total
                empresa = cells[11].get_text(strip=True)         # Empresa
                
                print(f"   Nr. Pedido: {nr_pedido}")
                print(f"   Cliente: {cliente[:40]}...")
                print(f"   Total (raw): {total_str}")
                
                # ✅ Converte o valor usando função robusta
                total = converter_valor_brasileiro(total_str)
                print(f"   Total (convertido): {total}")
                
                # ✅ Validação mínima: campos obrigatórios
                if not nr_pedido or not cliente or not data_pedido:
                    print(f"⚠️ Pedido ignorado por dados incompletos:")
                    print(f"   Nr.Ped: '{nr_pedido}', Cliente: '{cliente}', Data: '{data_pedido}'")
                    linhas_ignoradas += 1
                    continue
                
                # ✅ Validação do valor total
                try:
                    valor_float = float(total)
                    if valor_float <= 0:
                        print(f"⚠️ Pedido {nr_pedido} ignorado: valor inválido R$ {total}")
                        linhas_ignoradas += 1
                        continue
                except ValueError:
                    print(f"⚠️ Pedido {nr_pedido} ignorado: não foi possível converter total '{total_str}'")
                    linhas_ignoradas += 1
                    continue
                
                # ✅ Cria objeto do pedido (SEM duplicatas de vendedor)
                pedido = {
                    "Data": data_pedido,
                    "Entrega Prod.": entrega_prod if entrega_prod else "",  # ✅ Pode ser vazio
                    "Nr. Ped": nr_pedido,
                    "Cliente": cliente,
                    "Vendedor": vendedor,  # ✅ SÓ UMA VEZ!
                    "Total": total
                }
                pedidos.append(pedido)
                
                print(f"✅ Pedido {nr_pedido}: {cliente[:40]}... - R$ {total} | {vendedor[:30]}")
                
            except (IndexError, AttributeError, ValueError) as e:
                print(f"❌ Erro ao processar linha {linhas_processadas}: {e}")
                print(f"   Tipo de erro: {type(e).__name__}")
                linhas_ignoradas += 1
                import traceback
                traceback.print_exc()
                continue
        
        # 📊 Resumo do processamento
        print(f"\n{'='*60}")
        print(f"📊 RESUMO DO PROCESSAMENTO")
        print(f"{'='*60}")
        print(f"✅ Pedidos processados com sucesso: {len(pedidos)}")
        print(f"⚠️ Linhas ignoradas: {linhas_ignoradas}")
        print(f"📝 Total de linhas analisadas: {linhas_processadas}")
        print(f"{'='*60}\n")
        
        return pedidos
    
    except Exception as e:
        print(f"❌ Erro geral no processamento: {e}")
        import traceback
        traceback.print_exc()
        return []
